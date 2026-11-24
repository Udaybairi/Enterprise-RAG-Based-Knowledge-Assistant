# Evaluation report (2026-11-24)

Produced by `python -m app.evaluation.pipeline_eval` through the production code path.

## Provenance

| | |
|---|---|
| date | `2026-11-24T13:37:16+00:00` |
| git commit | `8166594` |
| prompt version | `a9b5f6d11cc4` |
| provider | `gemini` |
| chat model | `gemini-3.5-flash-lite` |
| utility model | `gemini-3.5-flash-lite` |
| fallback models | `['gemini-3.6-flash', 'gemini-3.5-flash']` |
| thinking level | `low` |
| embedding model | `gemini-embedding-001@768` |
| vector store | `pgvector` |
| database | `postgresql` |
| dataset size | `41` |
| dataset hash | `3596fbf24875` |
| corpus hash | `1d112c92b2be` |
| top k | `5` |
| reranker | `lexical` |
| similarity threshold | `0.0` |

## Retrieval (all questions with gold evidence)

| Chunking | Retrieval | Reranker | Chunks | Recall@1 | Recall@3 | Recall@k | Precision@k | MRR | nDCG@k | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | semantic | none | 15 | 0.800 | 1.000 | 1.000 | 0.206 | 0.895 | 0.922 | 9 | 10 |
| structure | hybrid | none | 15 | 0.829 | 1.000 | 1.000 | 0.206 | 0.914 | 0.937 | 9 | 11 |
| structure | keyword | none | 15 | 0.886 | 0.914 | 0.943 | 0.290 | 0.907 | 0.916 | 6 | 9 |
| structure | semantic | lexical | 15 | 0.857 | 1.000 | 1.000 | 0.206 | 0.929 | 0.947 | 11 | 12 |
| structure | hybrid | lexical | 15 | 0.857 | 1.000 | 1.000 | 0.206 | 0.929 | 0.947 | 11 | 15 |
| structure | keyword | lexical | 15 | 0.857 | 1.000 | 1.000 | 0.302 | 0.929 | 0.947 | 8 | 10 |
| recursive | semantic | none | 9 | 0.729 | 1.000 | 1.000 | 0.206 | 0.862 | 0.898 | 7 | 9 |
| recursive | hybrid | none | 9 | 0.786 | 0.971 | 0.971 | 0.200 | 0.886 | 0.908 | 7 | 10 |
| recursive | keyword | none | 9 | 0.800 | 0.914 | 0.971 | 0.314 | 0.870 | 0.895 | 6 | 9 |
| recursive | semantic | lexical | 9 | 0.800 | 0.971 | 1.000 | 0.206 | 0.887 | 0.915 | 10 | 13 |
| recursive | hybrid | lexical | 9 | 0.800 | 0.971 | 1.000 | 0.206 | 0.887 | 0.915 | 11 | 12 |
| recursive | keyword | lexical | 9 | 0.800 | 0.971 | 0.971 | 0.314 | 0.881 | 0.904 | 8 | 12 |
| semantic | semantic | none | 17 | 0.857 | 0.971 | 1.000 | 0.206 | 0.915 | 0.937 | 8 | 11 |
| semantic | hybrid | none | 17 | 0.800 | 0.971 | 0.971 | 0.200 | 0.881 | 0.904 | 9 | 14 |
| semantic | keyword | none | 17 | 0.829 | 0.914 | 0.943 | 0.299 | 0.877 | 0.894 | 7 | 9 |
| semantic | semantic | lexical | 17 | 0.829 | 0.971 | 1.000 | 0.206 | 0.907 | 0.931 | 11 | 13 |
| semantic | hybrid | lexical | 17 | 0.829 | 0.971 | 1.000 | 0.206 | 0.907 | 0.931 | 12 | 16 |
| semantic | keyword | lexical | 17 | 0.829 | 0.971 | 0.971 | 0.304 | 0.900 | 0.919 | 8 | 12 |

### Recall@k by question category

| Chunking | Retrieval | Reranker | adversarial | disambiguation | factual | multi_hop | numeric | paraphrase | table |
|---|---|---|---|---|---|---|---|---|---|
| structure | semantic | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| structure | hybrid | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| structure | keyword | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.778 | 1.000 |
| structure | semantic | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| structure | hybrid | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| structure | keyword | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| recursive | semantic | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| recursive | hybrid | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 1.000 |
| recursive | keyword | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 1.000 |
| recursive | semantic | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| recursive | hybrid | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| recursive | keyword | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 1.000 |
| semantic | semantic | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| semantic | hybrid | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 1.000 |
| semantic | keyword | none | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.778 | 1.000 |
| semantic | semantic | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| semantic | hybrid | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| semantic | keyword | lexical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.889 | 1.000 |

## Similarity-threshold calibration (semantic search, top 20)

**structure chunking** — recommended threshold `0.612`
(keeps evidence for 95% of answerable questions): `{"answerable_keeping_evidence": 0.943, "irrelevant_chunks_filtered": 0.914, "unanswerable_fully_filtered": 0.667}`

- best relevant cosine: `{"n": 35, "min": 0.581, "p25": 0.647, "median": 0.677, "max": 0.75}`
- irrelevant cosine: `{"n": 489, "min": 0.445, "p25": 0.52, "median": 0.546, "max": 0.687}`
- best cosine for unanswerable questions: `{"n": 6, "min": 0.576, "p25": 0.582, "median": 0.591, "max": 0.684}`

**recursive chunking** — recommended threshold `0.586`
(keeps evidence for 95% of answerable questions): `{"answerable_keeping_evidence": 0.943, "irrelevant_chunks_filtered": 0.828, "unanswerable_fully_filtered": 0.333}`

- best relevant cosine: `{"n": 35, "min": 0.583, "p25": 0.619, "median": 0.649, "max": 0.727}`
- irrelevant cosine: `{"n": 279, "min": 0.452, "p25": 0.526, "median": 0.549, "max": 0.686}`
- best cosine for unanswerable questions: `{"n": 6, "min": 0.56, "p25": 0.577, "median": 0.592, "max": 0.654}`

**semantic chunking** — recommended threshold `0.615`
(keeps evidence for 95% of answerable questions): `{"answerable_keeping_evidence": 0.943, "irrelevant_chunks_filtered": 0.921, "unanswerable_fully_filtered": 0.667}`

- best relevant cosine: `{"n": 35, "min": 0.581, "p25": 0.651, "median": 0.677, "max": 0.75}`
- irrelevant cosine: `{"n": 559, "min": 0.445, "p25": 0.522, "median": 0.545, "max": 0.687}`
- best cosine for unanswerable questions: `{"n": 6, "min": 0.573, "p25": 0.582, "median": 0.591, "max": 0.663}`

