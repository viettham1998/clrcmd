import random
from functools import partial

import pytest
from transformers import RobertaTokenizer

from src.simcse.data.dataset import EDASimCSEDataset, ESimCSEDataset, SimCSEDataset


@pytest.fixture
def corpus():
    return ["my name is seonghyeon", "how are you?", "i'm fine thank you. and you?"]


@pytest.fixture
def corpus_filepath(tmpdir, corpus):
    # Write corpus to temporary directory and return their filepath
    tmpfile = tmpdir.join("corpus.txt")
    tmpfile.write("\n".join(corpus))
    return tmpfile.strpath


@pytest.fixture
def tokenizer():
    return RobertaTokenizer.from_pretrained("roberta-base")


def test_tmpdir(tmpdir, corpus):
    tmpdir.join("corpus.txt").write("\n".join(corpus))
    assert tmpdir.join("corpus.txt").read() == "\n".join(corpus)


def test_simcse_dataset(corpus_filepath, tokenizer, corpus):
    # Create dataset
    dataset = SimCSEDataset(corpus_filepath, tokenizer)

    # Test dataset
    tokenize_fn = partial(
        tokenizer.encode_plus,
        padding="max_length",
        max_length=32,
        truncation=True,
    )
    assert len(dataset) == len(corpus)
    for i in range(len(dataset)):
        true = tokenize_fn(corpus[i])
        pred1, pred2 = dataset[i]
        assert pred1["input_ids"] == true["input_ids"]
        assert pred1["attention_mask"] == true["attention_mask"]
        assert pred2["input_ids"] == true["input_ids"]
        assert pred2["attention_mask"] == true["attention_mask"]


def test_esimcse_dataset(corpus_filepath, tokenizer):
    random.seed(0)
    # Create dataset
    dataset = ESimCSEDataset(corpus_filepath, tokenizer, 0.5)
    # fmt: off
    true_dataset = [
        ({"input_ids": [0, 4783, 766, 16, 842, 41860, 4717, 261, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
         {"input_ids": [0, 4783, 4783, 766, 16, 842, 842, 41860, 4717, 261, 261, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}),
        ({"input_ids": [0, 9178, 32, 47, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ]},
         {"input_ids": [0, 9178, 32, 47, 116, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}),
        ({"input_ids": [0, 118, 437, 2051, 3392, 47, 4, 8, 47, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
         {"input_ids": [0, 118, 437, 2051, 2051, 3392, 47, 47, 4, 8, 47, 47, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          "attention_mask": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]})
    ]
    assert len(dataset) == 3
    for i in range(len(dataset)):
        true1, true2 = true_dataset[i]
        pred1, pred2 = dataset[i]
        assert pred1["input_ids"] == true1["input_ids"]
        assert pred1["attention_mask"] == true1["attention_mask"]
        assert pred2["input_ids"] == true2["input_ids"]
        assert pred2["attention_mask"] == true2["attention_mask"]


def test_edasimcse_dataset(corpus_filepath, tokenizer):
    random.seed(0)
    # Create dataset
    dataset = EDASimCSEDataset(corpus_filepath, tokenizer)
    # fmt: off
    true_dataset = [
        ({'input_ids': [0, 4783, 766, 16, 842, 41860, 4717, 261, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
         {'input_ids': [0, 4783, 766, 842, 41860, 4717, 261, 16, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}),
        ({'input_ids': [0, 9178, 32, 47, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
         {'input_ids': [0, 9178, 32, 47, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}),
        ({'input_ids': [0, 118, 437, 2051, 3392, 47, 4, 8, 47, 116, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
         {'input_ids': [0, 757, 2051, 3392, 8, 47, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
          'attention_mask': [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}),
    ]
    assert len(dataset) == 3
    for i in range(len(dataset)):
        true1, true2 = true_dataset[i]
        pred1, pred2 = dataset[i]
        assert pred1["input_ids"] == true1["input_ids"]
        assert pred1["attention_mask"] == true1["attention_mask"]
        assert pred2["input_ids"] == true2["input_ids"]
        assert pred2["attention_mask"] == true2["attention_mask"]