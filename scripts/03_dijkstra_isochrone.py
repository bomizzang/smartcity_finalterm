# -*- coding: utf-8 -*-
"""
03_dijkstra_isochrone.py

수도권 지하철 네트워크 데이터(nodes.tsv, links.tsv)를 그래프로 구성하고,
핵심역을 출발점으로 다익스트라 최단시간 탐색을 수행하여 30분/60분 등시간권을 산출한다.
도달 가능한 각 역에 1km 버퍼를 씌워 합친 뒤, 등시간권 폴리곤으로 저장하고,
시군구 경계와 결합하여 등시간권 내 인구·종사자도 함께 추정한다.

입력:
  - subway_network.zip 안의 network/nodes.tsv, network/links.tsv
  - 시군구 경계 SHP (bnd_sigungu_*.shp)
  - 시군구 단위 인구/종사자 통계 CSV

출력:
  - {station}_iso{minutes}.geojson (등시간권 폴리곤)
  - 도달가능 인구·종사자 표준출력

사용 예:
  python 03_dijkstra_isochrone.py \
      --nodes network/nodes.tsv --links network/links.tsv \
      --station 판교 --minutes 30 60 \
      --sigungu-shp bnd_sigungu_00_2025_2Q.shp \
      --pop-csv 인구총괄_총인구.csv --emp-csv 종사자수.csv \
      --as-of 2026-05-04
"""

import argparse
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import Point
from shapely.ops import unary_union


def build_graph(nodes, links, as_of):
    # effective_begin이 있으면 그 값을, 없으면 begin을 기준으로 "as_of 시점에 운영 중인지" 판단
    nodes_eff = nodes["effective_begin"].fillna("").replace("", np.nan).fillna(nodes["begin"])
    active_nodes = nodes[nodes_eff <= as_of].copy()
    active_ids = set(active_nodes["id"])

    active_links = links[
        (links["begin"] <= as_of)
        & links["fromNode"].isin(active_ids)
        & links["toNode"].isin(active_ids)
    ].copy()

    n = len(nodes)
    u = active_links["fromNode"].to_numpy()
    v = active_links["toNode"].to_numpy()
    # 양방향 그래프로 구성 (지하철은 양방향 운행)
    src = np.concatenate([u, v])
    dst = np.concatenate([v, u])
    cost = np.concatenate(
        [active_links["timeFT"].to_numpy(), active_links["timeTF"].to_numpy()]
    ).astype(np.float32)
    return csr_matrix((cost, (src, dst)), shape=(n, n))


def isochrone_polygon(nodes, graph, start_ids, minutes, buffer_m=1000):
    sol = dijkstra(graph, indices=start_ids, min_only=True)
    seconds = minutes * 60
    nodes_idx = nodes.set_index("id")
    reachable_ids = [i for i in np.where(sol <= seconds)[0] if i in nodes_idx.index]
    sub = nodes_idx.loc[reachable_ids]

    pts = [Point(xy) for xy in zip(sub["lng"], sub["lat"])]
    gdf = gpd.GeoDataFrame(sub, geometry=pts, crs="EPSG:4326").to_crs(epsg=5179)
    buffered = unary_union(gdf.geometry.buffer(buffer_m).tolist())
    poly_wgs = gpd.GeoDataFrame({"geometry": [buffered]}, crs="EPSG:5179").to_crs(epsg=4326)
    return poly_wgs, len(sub)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--links", required=True)
    ap.add_argument("--station", required=True, help="핵심역 이름 (statnm 컬럼 값)")
    ap.add_argument("--minutes", nargs="+", type=int, default=[30, 60])
    ap.add_argument("--as-of", required=True, help="기준 시점 YYYY-MM-DD")
    ap.add_argument("--sigungu-shp", help="시군구 경계 SHP (인구·종사자 결합 시 필요)")
    ap.add_argument("--pop-csv", help="시군구 단위 인구 통계 CSV")
    ap.add_argument("--emp-csv", help="시군구 단위 종사자 통계 CSV")
    args = ap.parse_args()

    nodes = pd.read_csv(args.nodes, sep="\t")
    links = pd.read_csv(args.links, sep="\t")
    graph = build_graph(nodes, links, args.as_of)

    start_ids = nodes[nodes["statnm"] == args.station]["id"].tolist()
    if not start_ids:
        raise SystemExit(f"역 이름을 찾을 수 없음: {args.station}")

    sigungu = gpd.read_file(args.sigungu_shp) if args.sigungu_shp else None

    for m in args.minutes:
        poly, n_stations = isochrone_polygon(nodes, graph, start_ids, m)
        out_path = f"{args.station}_iso{m}.geojson"
        poly.to_file(out_path, driver="GeoJSON")
        print(f"[{m}분] 도달역 {n_stations}개, 폴리곤 저장: {out_path}")

        if sigungu is not None and args.pop_csv and args.emp_csv:
            poly_m = poly.to_crs(sigungu.crs).geometry.iloc[0]
            sg = sigungu.copy()
            sg["overlap_ratio"] = sg.geometry.intersection(poly_m).area / sg.geometry.area
            relevant = sg[sg["overlap_ratio"] > 0.001].copy()
            relevant["SIGUNGU_CD"] = relevant["SIGUNGU_CD"].astype(str)

            pop = pd.read_csv(args.pop_csv, header=None, names=["year", "code", "indicator", "value"])
            pop = pop[pop["indicator"] == "to_in_001"]
            pop["code"] = pop["code"].astype(str)

            emp = pd.read_csv(args.emp_csv, header=None, names=["year", "code", "indicator", "value"])
            emp["code"] = emp["code"].astype(str)
            emp["value"] = pd.to_numeric(emp["value"], errors="coerce")

            pop_alloc = relevant.merge(pop, left_on="SIGUNGU_CD", right_on="code")
            emp_alloc = relevant.merge(emp, left_on="SIGUNGU_CD", right_on="code")

            pop_total = (pop_alloc["value"] * pop_alloc["overlap_ratio"]).sum()
            emp_total = (emp_alloc["value"] * emp_alloc["overlap_ratio"]).sum()
            print(f"       도달가능 인구 {pop_total:,.0f}명, 종사자 {emp_total:,.0f}명")


if __name__ == "__main__":
    main()
