# -*- coding: utf-8 -*-
"""
04_industry_classification.py

SGIS 집계구 통계의 10차 표준산업분류 대분류 코드(cp_bem_001~019)는
코드 자체에 산업명이 적혀있지 않다. 이 코드가 KSIC(한국표준산업분류) 10차
대분류 19개(A~S)와 같은 순서로 매겨진다는 점을 이용해 산업명을 매핑하고,
분석 경계 내 집계구의 종사자수를 면적비례로 배분·합산하여 업종 구성비를 구한다.

입력:
  - SGIS 집계구 경계 SHP
  - SGIS 산업분류별(10차 대분류) 종사자수 CSV (cp_bem_001~019 포함)
  - 분석 경계 geojson

출력:
  - 업종별 종사자수·비율 (표준출력 + csv)

사용 예:
  python 04_industry_classification.py \
      --boundary-shp bnd_oa_31023_2025_2Q.shp \
      --emp-csv 31023_2023년_산업분류별(10차_대분류)_종사자수.csv \
      --boundary pangyo_final.geojson \
      --label pangyo
"""

import argparse
import geopandas as gpd
import pandas as pd

# KSIC 10차 대분류 표준 순서 (A~S, 19개).
# cp_bem_001 = A(농업,임업및어업), cp_bem_002 = B(광업) ... 순서로 매핑된다.
KSIC_ORDER = [
    "농업,임업및어업", "광업", "제조업", "전기,가스,증기및공기조절공급업",
    "수도,하수및폐기물처리,원료재생업", "건설업", "도매및소매업", "운수및창고업",
    "숙박및음식점업", "정보통신업", "금융및보험업", "부동산업",
    "전문,과학및기술서비스업", "사업시설관리,사업지원및임대서비스업",
    "공공행정,국방및사회보장행정", "교육서비스업", "보건업및사회복지서비스업",
    "예술,스포츠및여가관련서비스업", "협회및단체,수리및기타개인서비스업",
]
CODE_TO_INDUSTRY = {f"cp_bem_{i+1:03d}": name for i, name in enumerate(KSIC_ORDER)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boundary-shp", required=True)
    ap.add_argument("--emp-csv", required=True)
    ap.add_argument("--boundary", required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    sigungu = gpd.read_file(args.boundary_shp)
    boundary = gpd.read_file(args.boundary).to_crs(sigungu.crs)
    boundary_geom = boundary.geometry.unary_union

    sigungu["overlap_ratio"] = (
        sigungu.geometry.intersection(boundary_geom).area / sigungu.geometry.area
    )
    relevant = sigungu[sigungu["overlap_ratio"] > 0.001].copy()
    code_col = "TOT_OA_CD" if "TOT_OA_CD" in relevant.columns else "ADM_CD"
    relevant[code_col] = relevant[code_col].astype(str)

    emp = pd.read_csv(args.emp_csv, header=None, names=["year", "code", "indicator", "value"])
    emp["code"] = emp["code"].astype(str)
    emp["value"] = pd.to_numeric(emp["value"], errors="coerce").fillna(0)

    merged = relevant.merge(emp, left_on=code_col, right_on="code")
    merged["allocated"] = merged["value"] * merged["overlap_ratio"]
    merged["industry"] = merged["indicator"].map(CODE_TO_INDUSTRY)

    by_industry = merged.groupby("industry")["allocated"].sum().sort_values(ascending=False)
    total = by_industry.sum()

    print(f"[{args.label}] 업종별 종사자 구성 (추정, 총 {total:,.0f}명)")
    for name, value in by_industry.items():
        if value > 0:
            print(f"  {name:35s} {value:>10,.0f}명  ({value/total*100:5.1f}%)")

    out = by_industry.reset_index()
    out.columns = ["industry", "employment_estimate"]
    out["pct"] = (out["employment_estimate"] / total * 100).round(1)
    out.to_csv(f"{args.label}_industry_composition.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
