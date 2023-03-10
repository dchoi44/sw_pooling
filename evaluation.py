import argparse
import torch
import logging
import os
import pathlib
import random
import json

from beir import util, LoggingHandler
from beir.datasets.data_loader import GenericDataLoader
from beir.retrieval import models
from beir.retrieval.evaluation import EvaluateRetrieval
from beir.retrieval.search.dense import DenseRetrievalExactSearch as DRES

from custom_bert import CustomBERT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pooling', type=str, help='pooling method: one of [mean, max, cls]')
    parser.add_argument('--gpu', type=int, help='specify gpu number')
    parser.add_argument('--custom_pooling', type=bool, help='whether to use custom pooling or not')
    parser.add_argument('--sw_mode', type=str, default='nltk', help='stopwords list: default=nltk')
    parser.add_argument('--medical_dataset', action='store_true', help='if set, only eval on medical datasets')
    args = parser.parse_args()
    torch.cuda.set_device(args.gpu)
    assert args.pooling in {'mean', 'max', 'cls'}, \
        f"{args.pooling}-pooling not supported. choose between mean, max, cls"

    #### Just some code to print debug information to stdout
    logging.basicConfig(format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO,
                        handlers=[LoggingHandler()])
    #### /print debug information to stdout

    #### Dense Retrieval using SBERT (Sentence-BERT) ####
    #### Provide any pretrained sentence-transformers model
    #### The model was fine-tuned using cosine-similarity.
    #### Complete list - https://www.sbert.net/docs/pretrained_models.html
    if not args.custom_pooling:
        model_save_path = os.path.join(pathlib.Path(__file__).parent.absolute(), "output",
                                       "bert-base-uncased-v1-msmarco-{}".format(args.pooling))
        model = DRES(models.SentenceBERT(model_save_path), batch_size=16)
    else:
        model_save_path = os.path.join(pathlib.Path(__file__).parent.absolute(), "output",
                                       "bert-base-uncased-v1-msmarco-custom_{}_{}".format(args.sw_mode, args.pooling))
        model = DRES(CustomBERT(model_save_path), batch_size=16)

    retriever = EvaluateRetrieval(model, score_function="dot")

    scores = {}
    dataset_list = ["msmarco", "trec-covid", "nfcorpus", "nq", "hotpotqa", "fiqa", "arguana", "webis-touche2020",
                    "quora", "dbpedia-entity", "scidocs", "fever", "climate-fever", "scifact"]
    if args.medical_dataset:
        dataset_list = ['trec-covid', 'nfcorpus', 'scifact', 'scidocs']

    for dataset in dataset_list:
        #### Download nfcorpus.zip dataset and unzip the dataset
        url = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{}.zip".format(dataset)
        out_dir = os.path.join(pathlib.Path(__file__).parent.absolute(), "datasets")
        data_path = util.download_and_unzip(url, out_dir)

        #### Provide the data path where nfcorpus has been downloaded and unzipped to the data loader
        # data folder would contain these files:
        # (1) nfcorpus/corpus.jsonl  (format: jsonlines)
        # (2) nfcorpus/queries.jsonl (format: jsonlines)
        # (3) nfcorpus/qrels/test.tsv (format: tsv ("\t"))

        corpus, queries, qrels = GenericDataLoader(data_folder=data_path).load(split="test")

        #### Retrieve dense results (format of results is identical to qrels)
        results = retriever.retrieve(corpus, queries)

        #### Evaluate your retrieval using NDCG@k, MAP@K ...

        logging.info("Retriever evaluation for k in: {}".format(retriever.k_values))
        ndcg, _map, recall, precision = retriever.evaluate(qrels, results, retriever.k_values)

        mrr = retriever.evaluate_custom(qrels, results, retriever.k_values, metric="mrr")
        recall_cap = retriever.evaluate_custom(qrels, results, retriever.k_values, metric="r_cap")
        hole = retriever.evaluate_custom(qrels, results, retriever.k_values, metric="hole")

        scores[dataset] = {"ndcg": ndcg,
                           "map": _map,
                           "recall": recall,
                           "precision": precision,
                           "mrr": mrr,
                           "recall_cap": recall_cap,
                           "hole": hole}

        #### Print top-k documents retrieved ####
        top_k = 10

        query_id, ranking_scores = random.choice(list(results.items()))
        scores_sorted = sorted(ranking_scores.items(), key=lambda item: item[1], reverse=True)
        logging.info("Query : %s\n" % queries[query_id])

        for rank in range(top_k):
            doc_id = scores_sorted[rank][0]
            # Format: Rank x: ID [Title] Body
            logging.info("Rank %d: %s [%s] - %s\n" % (rank+1, doc_id, corpus[doc_id].get("title"), corpus[doc_id].get("text")))

    eval_save_path = os.path.join(model_save_path, 'eval')
    with open(os.path.join(eval_save_path, 'score.json'), 'w') as f:
        json.dump(scores, f)


if __name__ == '__main__':
    main()
