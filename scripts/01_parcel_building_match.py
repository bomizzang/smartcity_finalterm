# -*- coding: utf-8 -*-
"""
01_parcel_building_match.py

연속지적도(SHP)와 분석 경계(GeoJSON)를 겹쳐서, 경계 안에 들어가는 필지를 추려내고
건축HUB 건축물대장(CSV)과 번지수로 매칭한다.

입력:
  - 연속지적도_*.zip 안의 .shp (예: LSMD_CONT_LDREG_41135_202606.shp)
  - 건축물대장_*.csv (건축HUB에서 다운로드, 시군구 단위)
  - 분석 경계 geojson (예: pangyo_final.geojson)

출력:
  - 경계 내 필지 목록 csv (번지, 지목, 면적)
  - 필지 + 건물 속성이 합쳐진 geojson (지도 클릭 인터랙션용)

사용 예:
  python 01_parcel_building_match.py \
      --cadaster LSMD_CONT_LDREG_41135_202606.shp \
      --building 건축물대장_분당구.csv \
      --boundary pangyo_final.geojson \
      --dong-code 4113510900 \
      --out-prefix pangyo
"""

import argparse
import geopandas as gpd
import pandas as pd
import shapely.geometry as geom


def parse_jibun(jibun_text):
    """'633-1 도' 같은 지번 문자열을 (본번, 부번, 지목)으로 분리."""
    s = jibun_text.strip().replace("산", "")
    jimok = s[-1]
    num = s[:-1].strip()
    try:
        if "-" in num:
            bon, bu = num.split("-")
            return int(bon), int(bu), jimok
        return int(num), 0, jimok
    except ValueError:
        return -1, -1, jimok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cadaster", required=True, help="연속지적도 .shp 경로")
    ap.add_argument("--building", required=True, help="건축물대장 .csv 경로")
    ap.add_argument("--boundary", required=True, help="분석 경계 .geojson 경로")
    ap.add_argument("--dong-code", required=True, help="법정동코드 10자리 (PNU 앞 10자리)")
    ap.add_argument("--overlap-threshold", type=float, default=0.5, help="필지 채택 최소 교차비율")
    ap.add_argument("--out-prefix", required=True, help="출력 파일 이름 접두사")
    args = ap.parse_args()

    # 1) 지적도를 미터 좌표계(EPSG:5186, 측지계는 원본 그대로)로 읽어 정확한 면적을 계산
    cad_proj = gpd.read_file(args.cadaster)
    cad_proj["area_m2"] = cad_proj.geometry.area
    cad_proj = cad_proj[cad_proj["PNU"].str.startswith(args.dong_code)].copy()

    # 2) 분석 경계와의 교차면적 비율로 "경계 내 필지" 판단 (다수겹침 원칙)
    boundary_gdf = gpd.read_file(args.boundary).to_crs(cad_proj.crs)
    boundary_geom = boundary_gdf.geometry.unary_union

    cad_proj["overlap_area"] = cad_proj.geometry.intersection(boundary_geom).area
    cad_proj["overlap_ratio"] = cad_proj["overlap_area"] / cad_proj["area_m2"]
    within = cad_proj[cad_proj["overlap_ratio"] > args.overlap_threshold].copy()

    parsed = within["JIBUN"].apply(parse_jibun)
    within["bonbun"] = parsed.apply(lambda x: x[0])
    within["bubun"] = parsed.apply(lambda x: x[1])
    within["jimok"] = parsed.apply(lambda x: x[2])

    print(f"[1/3] 경계 내 필지 {len(within)}개 (교차비율 {args.overlap_threshold*100:.0f}% 이상)")
    within[["JIBUN", "bonbun", "bubun", "jimok", "area_m2"]].to_csv(
        f"{args.out_prefix}_lots.csv", index=False
    )

    # 3) 건축물대장과 (본번, 부번)으로 매칭
    building = pd.read_csv(args.building, encoding="utf-8-sig")
    agg = building.groupby(["번", "지"]).agg(
        건물명=("건물명", lambda x: "; ".join(x.dropna().unique()[:2]) if len(x.dropna()) else ""),
        주용도=("주용도", lambda x: x.mode().iloc[0] if len(x.mode()) else ""),
        연면적=("연면적(㎡)", "sum"),
        건폐율=("건폐율(%)", "mean"),
        용적률=("용적률(%)", "mean"),
        지상층수=("지상층수", "max"),
    ).reset_index()

    merged = within.merge(agg, left_on=["bonbun", "bubun"], right_on=["번", "지"], how="left")
    merged["건물명"] = merged["건물명"].fillna("").replace("", "(건물 없음 / 나대지)")
    merged["주용도"] = merged["주용도"].fillna("나대지")
    for col in ["연면적", "건폐율", "용적률"]:
        merged[col] = merged[col].fillna(0).round(1)
    merged["지상층수"] = merged["지상층수"].fillna(0).astype(int)
    merged["area_m2"] = merged["area_m2"].round(0)

    out_cols = ["JIBUN", "건물명", "주용도", "연면적", "건폐율", "용적률", "지상층수", "area_m2", "geometry"]
    merged_wgs = merged.to_crs(epsg=4326)
    merged_wgs[out_cols].to_file(f"{args.out_prefix}_parcels.geojson", driver="GeoJSON")
    print(f"[2/3] 필지+건물 속성 geojson 저장: {args.out_prefix}_parcels.geojson")

    # 4) 공지율(미건축 비율) 요약 출력
    dae_only = within[within["jimok"] == "대"]
    has_building = dae_only.apply(
        lambda r: ((r["bonbun"], r["bubun"]) in set(zip(agg["번"], agg["지"]))), axis=1
    )
    vacant_ratio = (1 - has_building.mean()) * 100 if len(dae_only) else 0
    print(f"[3/3] 대지 필지 {len(dae_only)}개 중 공지율 {vacant_ratio:.1f}%")


if __name__ == "__main__":
    main()
