from dataclasses import dataclass
import logging
from typing import Callable, List, Tuple

import torch
import torch.distributed as dist
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from transformers.modeling_outputs import BaseModelOutput
from transformers.models.roberta.modeling_roberta import (
    RobertaModel,
    RobertaPreTrainedModel,
)

logger = logging.getLogger(__name__)


@dataclass
class BaseModelOutputWithHead(BaseModelOutput):
    last_hidden_state: torch.FloatTensor = None
    hidden_states: Tuple[torch.FloatTensor] = None
    token_output: torch.FloatTensor = None


class Pooler(nn.Module):
    """Poolers to get the sentence embedding
    'cls': [CLS] representation with BERT/RoBERTa's MLP pooler.
    'cls_before_pooler': [CLS] representation without the original MLP pooler.
    'avg': average of the last layers' hidden states at each token.
    'avg_top2': average of the last two layers.
    'avg_first_last': average of the first and the last layers.
    """

    def __init__(self, pooler_type: str):
        super().__init__()
        self.pooler_type = pooler_type
        assert self.pooler_type in [
            "cls",
            "cls_before_pooler",
            "avg",
            "avg_top2",
            "avg_first_last",
        ], f"unrecognized pooling type {self.pooler_type}"

    def forward(
        self,
        attention_mask: Tensor,
        outputs: BaseModelOutputWithHead,
    ) -> Tensor:
        if self.pooler_type == "cls":
            if self.training:
                return outputs.token_output[:, 0]
            else:
                return outputs.last_hidden_state[:, 0]
        elif self.pooler_type == "cls_before_pooler":
            return outputs.last_hidden_state[:, 0]
        elif self.pooler_type == "avg":
            last_hidden = outputs.last_hidden_state
            attention_mask = attention_mask[:, :, None]
            hidden = last_hidden * attention_mask
            pooled_sum = hidden.sum(dim=1)
            masked_sum = attention_mask.sum(dim=1)
            return pooled_sum / masked_sum
        elif self.pooler_type == "avg_first_last":
            hidden_states = outputs.hidden_states
            attention_mask = attention_mask[:, :, None]
            hidden = (hidden_states[0] + hidden_states[-1]) / 2.0
            hidden = hidden * attention_mask
            pooled_sum = hidden.sum(dim=1)
            masked_sum = attention_mask.sum(dim=1)
            return pooled_sum / masked_sum
        elif self.pooler_type == "avg_top2":
            hidden_states = outputs.hidden_states
            attention_mask = attention_mask[:, :, None]
            hidden = (hidden_states[-1] + hidden_states[-2]) / 2.0
            hidden = hidden * attention_mask
            pooled_sum = hidden.sum(dim=1)
            masked_sum = attention_mask.sum(dim=1)
            return pooled_sum / masked_sum
        else:
            raise NotImplementedError()


def cl_init(cls, config):
    """
    Contrastive learning class init function.
    """
    cls.pooler_type = cls.model_args.pooler_type
    cls.pooler = Pooler(cls.model_args.pooler_type)
    cls.mlp = nn.Sequential(
        nn.Linear(config.hidden_size, config.hidden_size),
        nn.Tanh(),
    )
    cls.init_weights()


def dist_all_gather(x: Tensor) -> Tensor:
    """Boilerplate code for all gather in distributed setting

    :param x: Tensor to be gathered
    :type x: Tensor
    :return: Tensor after gathered. For the gradient flow, current rank is
             replaced to original tensor
    :rtype: Tensor
    """
    xlist = [torch.zeros_like(x) for _ in range(dist.get_world_size())]
    dist.all_gather(tensor_list=xlist, tensor=x.contiguous())
    # Since `all_gather` results do not have gradients, we replace the
    # current process's corresponding embeddings with original tensors
    xlist[dist.get_rank()] = x
    return torch.cat(xlist, dim=0)


def compute_loss_simclr(
    output1: BaseModelOutputWithHead,
    output2: BaseModelOutputWithHead,
    attention_mask1: Tensor,
    attention_mask2: Tensor,
    pooler_fn: Callable,
    temp: float,
    is_training: bool,
) -> Tensor:
    """Compute SimCLR loss in sentence-level

    :param output1: Model output for first view
    :type output1: BaseModelOutputWithPooling
    :param output2: Model output for second view
    :type output2: BaseModelOutputWithPooling
    :param attention_mask1: Attention mask
    :type attention_mask1: FloatTensor(batch_size, seq_len)
    :param attention_mask2: Attention mask
    :type attention_mask2: FloatTensor(batch_size, seq_len)
    :param pooler_fn: Function for extracting sentence representation
    :type pooler_fn: Callable[[Tensor, BaseModelOutputWithHead],
                              FloatTensor(batch_size, hidden_dim)]
    :param temp: Temperature for cosine similarity
    :type temp: float
    :param is_training: Flag indicating whether is training or not
    :type is_training: bool
    :return: Scalar loss
    :rtype: FloatTensor()
    """
    output1 = pooler_fn(attention_mask1, output1)
    output2 = pooler_fn(attention_mask2, output2)
    # Gather all embeddings if using distributed training
    if dist.is_initialized() and is_training:
        output1, output2 = dist_all_gather(output1), dist_all_gather(output2)

    sim = F.cosine_similarity(output1[None, :, :], output2[:, None, :], dim=2)
    sim = sim / temp
    # (batch_size, batch_size)
    labels = torch.arange(sim.shape[1], dtype=torch.long, device=sim.device)
    loss = F.cross_entropy(sim, labels)
    logger.debug(f"{loss = :.4f}")
    return loss


def compute_loss_simclr_token(
    input1: Tensor,
    input2: Tensor,
    output1: Tensor,
    output2: Tensor,
    pairs: List[Tensor],
    temp: float,
    is_training: bool,
) -> Tensor:
    """Compute SimCLR loss in token-level

    :param input1: Bert input for the first sentence
    :type input1: LongTensor(batch_size, seq_len)
    :param input2: Bert input for the second sentence
    :type input2: LongTensor(batch_size, seq_len)
    :param output1: Bert output for the first sentence
    :type output1: FloatTensor(batch_size, seq_len, hidden_dim)
    :param ouptut2: Bert output for the second sentence
    :type output2: FloatTensor(batch_size, seq_len, hidden_dim)
    :param pairs: Pair for computing similarity between token
    :type pairs: List[LongTensor(num_pairs, 2)]
    :param temp: Temperature for cosine similarity
    :type temp: float
    :param is_training: indicator whether training or not
    :type is_training: bool
    :return: Scalar loss
    :rtype: FloatTensor()
    """
    # Gather all embeddings if using distributed training
    # if dist.is_initialized() and is_training:
    #    output1, output2 = dist_all_gather(output1), dist_all_gather(output2)
    assert input1.shape[0] == input2.shape[0] == len(pairs)
    assert output1.shape[0] == output2.shape[0] == len(pairs)
    assert input1.shape[1] == output1.shape[1]
    assert input2.shape[1] == output2.shape[1]
    batch_idx = [torch.full((x.shape[0],), i) for i, x in enumerate(pairs)]
    seq_idx1 = [x[:, 0] for x in pairs]
    seq_idx2 = [x[:, 1] for x in pairs]
    batch_idx = torch.cat(batch_idx)
    seq_idx1 = torch.cat(seq_idx1)
    seq_idx2 = torch.cat(seq_idx2)
    assert batch_idx.shape == seq_idx1.shape == seq_idx2.shape
    input1, input2 = input1[batch_idx, seq_idx1], input2[batch_idx, seq_idx2]
    # (num_pairs,)
    output1 = output1[batch_idx, seq_idx1]
    output2 = output2[batch_idx, seq_idx2]
    # (num_pairs, hidden_dim)
    assert torch.equal(input1, input2), "Different input pair is not supported"
    sorted_token, sorted_indice = torch.sort(input1)
    sorted_token_mask = sorted_token < 10
    sorted_token = sorted_token[sorted_token_mask]
    batch_idx = batch_idx[sorted_indice][sorted_token_mask]
    output1 = output1[sorted_indice][sorted_token_mask, :]
    output2 = output2[sorted_indice][sorted_token_mask, :]
    val, counts = torch.unique(sorted_token, sorted=True, return_counts=True)
    counts = counts.tolist()
    batch_idx = torch.split(batch_idx, counts)
    output1 = torch.split(output1, counts)
    output2 = torch.split(output2, counts)
    # print(f"val: {val}\ncounts: {counts}")
    # print(f"sorted_token: {sorted_token}")
    # output1 = [x for x in output1 if x.shape[0] > 20]
    # output2 = [x for x in output2 if x.shape[0] > 20]
    # batch_idx = [x for x in batch_idx if x.shape[0] > 20]
    # list(FloatTensor(num_pairs_per_symbol, hidden_dim))
    # batch_idx = batch_idx[0:1]
    # output1 = output1[0:1]
    # output2 = output2[0:1]
    # print(f"{batch_idx = }")
    # Calculate temperature aware cosine similarity
    sim = [
        F.cosine_similarity(x1[None, :, :], x2[:, None, :], dim=2) / temp
        for x1, x2 in zip(output1, output2)
    ]
    # list(FloatTensor(num_pairs_per_symbol, num_pairs_per_symbol))
    label = [
        torch.arange(x.shape[1], dtype=torch.long, device=x.device)
        for x in sim
    ]
    loss = torch.stack([F.cross_entropy(x, l) for x, l in zip(sim, label)])
    loss = loss.mean()
    # loss = F.mse_loss(output1, output2)
    # logger.info(f"{loss = :.4f}")
    return loss


def compute_representation(
    encoder: Callable,
    mlp: nn.Module,
    input_ids: Tensor,
    attention_mask: Tensor,
    token_type_ids: Tensor,
) -> Tuple[BaseModelOutputWithHead, BaseModelOutputWithHead]:
    """Compute bert contextual representation for contrastive learning"""
    batch_size = input_ids.shape[0]
    input_ids = torch.cat([input_ids[:, 0], input_ids[:, 1]])
    attention_mask = torch.cat([attention_mask[:, 0], attention_mask[:, 1]])
    if token_type_ids is not None:
        token_type_ids = torch.cat(
            [token_type_ids[:, 0], token_type_ids[:, 1]]
        )
    outputs = encoder(
        input_ids,
        attention_mask=attention_mask,
        token_type_ids=token_type_ids,
        return_dict=True,
    )
    token_output = mlp(outputs.last_hidden_state)
    token_output1 = token_output[:batch_size]
    token_output2 = token_output[batch_size:]
    last_hidden1 = outputs.last_hidden_state[:batch_size]
    last_hidden2 = outputs.last_hidden_state[batch_size:]
    if outputs.hidden_states is not None:
        hidden_states1 = tuple(x[:batch_size] for x in outputs.hidden_states)
        hidden_states2 = tuple(x[batch_size:] for x in outputs.hidden_states)
    else:
        hidden_states1, hidden_states2 = None, None
    outputs1 = BaseModelOutputWithHead(
        last_hidden_state=last_hidden1,
        hidden_states=hidden_states1,
        token_output=token_output1,
    )
    outputs2 = BaseModelOutputWithHead(
        last_hidden_state=last_hidden2,
        hidden_states=hidden_states2,
        token_output=token_output2,
    )
    return outputs1, outputs2


def cl_forward(
    cls,
    encoder,
    input_ids=None,
    attention_mask=None,
    token_type_ids=None,
    pairs=None,
) -> Tuple[Tensor]:
    input_ids1 = input_ids[:, 0]
    input_ids2 = input_ids[:, 1]
    if pairs is not None:
        batch_idx = [torch.full((x.shape[0],), i) for i, x in enumerate(pairs)]
        batch_idx = torch.cat(batch_idx)
        seq_idx1 = torch.cat([x[:, 0] for x in pairs])
        seq_idx2 = torch.cat([x[:, 1] for x in pairs])
        pair_left = input_ids1[batch_idx, seq_idx1]
        pair_right = input_ids2[batch_idx, seq_idx2]
        assert torch.equal(pair_left, pair_right)
    outputs1, outputs2 = compute_representation(
        encoder, cls.mlp, input_ids, attention_mask, token_type_ids
    )
    attention_mask1 = attention_mask[:, 0, :]
    attention_mask2 = attention_mask[:, 1, :]
    """
    loss = compute_loss_simclr(
        outputs1,
        outputs2,
        attention_mask1,
        attention_mask2,
        cls.pooler,
        cls.model_args.temp,
        cls.training,
    )
    """
    loss = 0
    if cls.model_args.loss_token:
        assert pairs is not None
        loss += cls.model_args.coeff_loss_token * compute_loss_simclr_token(
            input_ids1,
            input_ids2,
            outputs1.token_output,
            outputs2.token_output,
            pairs,
            cls.model_args.temp,
            cls.training,
        )

    return (loss,)


def sentemb_forward(
    cls, encoder, input_ids=None, attention_mask=None, token_type_ids=None
) -> BaseModelOutputWithHead:
    outputs = encoder(
        input_ids,
        attention_mask=attention_mask,
        token_type_ids=token_type_ids,
        return_dict=True,
    )
    token_output = cls.mlp(outputs.last_hidden_state)
    outputs = BaseModelOutputWithHead(
        last_hidden_state=outputs.last_hidden_state,
        hidden_states=outputs.hidden_states,
        token_output=token_output,
    )
    return outputs


class RobertaForCL(RobertaPreTrainedModel):
    _keys_to_ignore_on_load_missing = [r"position_ids"]

    def __init__(self, config, *model_args, **model_kwargs):
        super().__init__(config)
        self.model_args = model_kwargs["model_args"]
        self.roberta = RobertaModel(config)

        cl_init(self, config)

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        token_type_ids=None,
        pairs=None,
        sent_emb=False,
    ):
        if sent_emb:
            return sentemb_forward(
                self,
                self.roberta,
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            )
        else:
            return cl_forward(
                self,
                self.roberta,
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                pairs=pairs,
            )
