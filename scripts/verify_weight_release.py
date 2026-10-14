"""Cross-runtime production/oracle parity, using the frozen validation inputs."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
VALIDATION=ROOT/"artifacts/snapshots/production-weight-v3-validation-20261014"
REFERENCE=ROOT/"artifacts/snapshots/stage3-reference-weight-v3-20261014"
QA=ROOT/"artifacts/weight-v3-rollout-evidence"
read=lambda p:json.loads(p.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("phase",choices=["oracle","check"])
    args=parser.parse_args();QA.mkdir(parents=True,exist_ok=True)
    if args.phase=="oracle":
        import numpy as np
        from weight_reference import WeightReference
        engine=WeightReference(np.loadtxt(VALIDATION/"fit.csv",delimiter=","),(.1,1),mode="W")
        data=read(VALIDATION/"evaluation.json")
        cases=[]
        for r in data["random"]:
            cases.extend([r["base"],*r["variants"],r["deleted"]])
        for kind in ("N_boundary","H_boundary"):
            for r in data[kind]:cases.extend([r["before"],r["after"]])
        cases.extend([data["account"]["base"],*[r["score"] for r in data["account"]["variants"]]])
        expected=[]
        for s in cases:
            clean={k:v for k,v in s.items() if k!="old"}
            expected.append({"score":clean,"positions":engine.positions(s)})
        (QA/"oracle.json").write_text(json.dumps(expected,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        print("Frozen numerical oracle cases:",len(expected))
    else:
        from gamepersona.reference import reference_positions
        from gamepersona.scoring import sufficiency
        model,ref=read(REFERENCE/"model.json"),read(REFERENCE/"reference.json")
        expected=read(QA/"oracle.json")
        maximum=0.;comparisons=0
        for i,case in enumerate(expected):
            score={"read_status":"success","unknown_ratio":0,**case["score"]}
            assert sufficiency(score,model)==score["sufficiency_reasons"]
            computed=reference_positions(score,ref,model)
            for d,value in computed.items():
                target=case["positions"][d]
                assert value["reason"]==target["reason"],(i,d,value["reason"],target["reason"])
                if value["value"] is not None:
                    delta=abs(value["value"]-target["value"])
                    maximum=max(maximum,delta);comparisons+=1
                    assert delta<=1e-9,(i,d,delta)
            if i%500==0:print(f"Production/oracle: {i}/{len(expected)}",flush=True)
        result={"cases":len(expected),"supported_dimension_comparisons":comparisons,
                "max_absolute_percentile_delta":maximum,"passed":True}
        (QA/"parity.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result))


if __name__=="__main__":main()
