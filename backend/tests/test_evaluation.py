from __future__ import annotations

from app.evaluation import metrics as M
from app.evaluation.test_pipeline import run_evaluation


def test_metric_functions():
    r = M.retrieval_metrics([("noise", "a.md"), ("leave is 27 days of paid annual leave", "h.md")],
                            ["h.md"], ["27 days of paid annual leave"])
    assert r == {"precision": 0.5, "recall": 1.0, "hit_rate": 1.0, "mrr": 0.5}
    assert M.token_f1("27 days of leave", "Employees get 27 days of leave") > 0.6
    assert M.lexical_faithfulness("Leave is 27 days [1].", ["Annual leave is 27 days."]) == 1.0
    assert M.lexical_faithfulness("The moon is made of cheese.", ["Annual leave is 27 days."]) == 0.0


def test_strategy_comparison_runs(client, admin):
    res = run_evaluation(["recursive", "structure"], ["semantic", "hybrid"], top_k=3, evaluate_generation=True)
    assert len(res["configs"]) == 4
    for c in res["configs"]:
        m = c["metrics"]
        for key in ("precision", "recall", "mrr", "context_relevance", "faithfulness", "citation_accuracy",
                    "hallucination_rate", "refusal_accuracy", "answer_relevance", "latency_ms"):
            assert m[key] is not None, key
            if key != "latency_ms":
                assert 0.0 <= m[key] <= 1.0 or key == "context_relevance"
        assert m["recall"] >= 0.5  # the offline embedder still finds most evidence
    assert res["best"]["chunking"] in ("recursive", "structure")


def test_evaluation_api(client, admin):
    r = client.post("/api/evaluation/run", headers=admin[0], json={
        "chunking_strategies": ["structure"], "retrieval_strategies": ["hybrid"], "top_k": 3,
        "evaluate_generation": False})
    assert r.status_code == 202, r.text
    run = client.get(f"/api/evaluation/runs/{r.json()['id']}", headers=admin[0]).json()
    assert run["status"] == "completed", run
    assert run["results"]["configs"][0]["metrics"]["recall"] is not None
    assert client.get("/api/evaluation/dataset", headers=admin[0]).json()


def test_evaluation_runs_record_provenance(client, admin):
    from app.rag.prompts import PROMPT_VERSION

    res = run_evaluation(["structure"], ["hybrid"], top_k=3, evaluate_generation=False)
    p = res["provenance"]
    assert p["prompt_version"] == PROMPT_VERSION and p["provider"] == "fake"
    assert len(p["dataset_hash"]) == 12 and len(p["corpus_hash"]) == 12 and p["git_commit"]


def test_ndcg_and_stratified_order():
    from app.evaluation.metrics import ndcg_at_k
    from app.evaluation.pipeline_eval import stratified

    assert ndcg_at_k([True, False, False], 1, 3) == 1.0
    assert round(ndcg_at_k([False, True], 1, 2), 3) == 0.631
    assert ndcg_at_k([False, False], 1, 2) == 0.0
    data = [{"id": i, "category": c} for i, c in enumerate("aaabbc")]
    assert [d["category"] for d in stratified(data)][:3] == ["a", "b", "c"]
