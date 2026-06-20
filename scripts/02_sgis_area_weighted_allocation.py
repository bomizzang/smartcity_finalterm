# -*- coding: utf-8 -*-
"""
02_sgis_area_weighted_allocation.py

SGIS 통계지리정보서비스에서 받은 "집계구별 통계"(인구, 종사자, 가구 등)는
행정구역 전체 단위로 제공되기 때문에, 우리가 임의로 그린 분석 경계(예: 판교 66ha)와
정확히 겹치지 않는다. 이 스크립트는 집계구 경계와 분석 경계의 "겹치는 면적 비율"만큼
통계값을 비례 배분(area-weighted allocation)하여, 분석 경계 안의 추정값을 산출한다.

입력:
  - SGIS 통계지역경계 SHP (bnd_oa_*.shp, 집계구 폴리곤)
  - SGIS 통계자료 CSV (long format: year, code, indicator, value)
  - 분석 경계 geojson

출력:
  - 분석 경계 내 추정 통계값 (표준출력 + csv)

사용 예:
  python 02_sgis_area_weighted_allocation.py \
      --boundary-shp bnd_oa_31023_2025_2Q.shp \
      --stat-csv 31023_2024년_인구총괄(총인구).csv \
      --indicator to_in_001 \
      --boundary pangyo_final.geojson \
      --label "판교 인구"
"""

import argparse
import geopandas as gpd
import pandas as pd
import shapely.geometry as geom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boundary-shp", required=True, help="SGIS 집계구 경계 .shp")
    ap.add_argument("--stat-csv", required=True, help="SGIS 통계자료 .csv (long format)")
    ap.add_argument("--indicator", required=True, help="추출할 지표코드 (예: to_in_001)")
    ap.add_argument("--boundary", required=True, help="분석 경계 .geojson")
    ap.add_argument("--label", default="결과", help="출력 시 표시할 이름")
    args = ap.parse_args()

    # 1) 집계구 경계는 면적 계산을 위해 미터 좌표계(EPSG:5179)로 읽는다
    sigungu = gpd.read_file(args.boundary_shp)

    with_boundary = gpd.read_file(args.boundary).to_crs(sigungu.crs)
    boundary_geom = with_boundary.geometry.unary_union

    # 2) 각 집계구가 분석 경계와 겹치는 면적 비율 계산
    sigungu["overlap_area"] = sigungu.geometry.intersection(boundary_geom).area
    sigungu["overlap_ratio"] = sigungu["overlap_area"] / sigungu.geometry.area
    relevant = sigungu[sigungu["overlap_ratio"] > 0.001].copy()

    code_col = "TOT_OA_CD" if "TOT_OA_CD" in relevant.columns else "ADM_CD"
    relevant[code_col] = relevant[code_col].astype(str)

    print(f"[1/2] 분석 경계와 겹치는 집계구 {len(relevant)}개")

    # 3) 통계 CSV에서 해당 지표만 추출, 비율 곱해서 합산
    stat = pd.read_csv(args.stat_csv, header=None, names=["year", "code", "indicator", "value"])
    stat = stat[stat["indicator"] == args.indicator].copy()
    stat["code"] = stat["code"].astype(str)
    stat["value"] = pd.to_numeric(stat["value"], errors="coerce")

    merged = relevant.merge(stat, left_on=code_col, right_on="code", how="left")
    merged["allocated"] = merged["value"] * merged["overlap_ratio"]
    total = merged["allocated"].sum()

    print(f"[2/2] {args.label}: {total:,.0f}  (지표코드 {args.indicator})")
    merged[[code_col, "value", "overlap_ratio", "allocated"]].to_csv(
        f"{args.label.replace(' ', '_')}_allocation_detail.csv", index=False
    )


if __name__ == "__main__":
    main()
