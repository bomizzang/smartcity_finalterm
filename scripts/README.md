# 데이터 전처리 스크립트

판교/김포 비교분석에 사용한 핵심 전처리 로직을 실행 가능한 스크립트로 정리했다.
원본 작업은 분석 도중 단계별로 결과를 확인하며 진행했기 때문에, 이 스크립트들은
그 과정을 재현 가능한 형태로 다시 정리한 것이다. 실행에는 `geopandas`, `pandas`,
`scipy`, `shapely`가 필요하다.

```bash
pip install geopandas pandas scipy shapely
```

## 01_parcel_building_match.py — 필지·건축물 매칭

연속지적도(SHP)와 분석 경계(geojson)를 겹쳐서, 경계 안에 들어가는 필지만 추려낸다.
이때 필지가 경계에 살짝 걸치기만 한 경우(도로 등)까지 포함되지 않도록, **교차면적이
필지 전체 면적의 50% 이상인 경우만** 채택했다(다수겹침 원칙). 추려진 필지는 건축물대장의
법정동·번·지 컬럼으로 건물 정보(주용도, 연면적, 용적률 등)와 매칭되고, 매칭이 안 되는
필지는 "나대지"로 분류된다. 이 결과가 지도의 필지 클릭 인터랙션에 쓰인다.

```bash
python 01_parcel_building_match.py \
  --cadaster LSMD_CONT_LDREG_41135_202606.shp \
  --building 건축물대장_분당구.csv \
  --boundary pangyo_final.geojson \
  --dong-code 4113510900 \
  --out-prefix pangyo
```

## 02_sgis_area_weighted_allocation.py — 인구·종사자 면적비례 배분

SGIS 통계는 행정구역 단위(읍면동, 집계구)로만 제공되기 때문에 우리가 임의로 그린 경계와
정확히 일치하지 않는다. 이 스크립트는 집계구 경계와 분석 경계가 겹치는 면적 비율만큼
통계값을 나눠서 합산한다. 예를 들어 한 집계구의 60%가 분석 경계 안에 들어간다면, 그
집계구 인구의 60%만 우리 분석에 포함시키는 방식이다.

```bash
python 02_sgis_area_weighted_allocation.py \
  --boundary-shp bnd_oa_31023_2025_2Q.shp \
  --stat-csv 31023_2024년_인구총괄(총인구).csv \
  --indicator to_in_001 \
  --boundary pangyo_final.geojson \
  --label "판교 인구"
```

## 03_dijkstra_isochrone.py — 등시간권(다익스트라) 분석

지하철 노드/링크 데이터를 그래프로 만들어 핵심역에서 다익스트라 최단시간 탐색을 한다.
30분·60분 이내 도달 가능한 역들을 모아 각각 1km 반경 버퍼를 씌우고 하나로 합쳐서
등시간권 폴리곤을 만든다. 이 폴리곤을 다시 시군구 경계와 겹쳐서(02번과 같은 면적비례
배분 방식으로) 등시간권 내 인구·종사자수를 추정한다.

```bash
python 03_dijkstra_isochrone.py \
  --nodes network/nodes.tsv --links network/links.tsv \
  --station 판교 --minutes 30 60 \
  --sigungu-shp bnd_sigungu_00_2025_2Q.shp \
  --pop-csv 인구총괄_총인구.csv --emp-csv 종사자수.csv \
  --as-of 2026-05-04
```

## 04_industry_classification.py — 산업분류 구성

SGIS의 10차 표준산업분류 대분류 코드(`cp_bem_001` ~ `cp_bem_019`)는 코드 자체에 업종명이
적혀 있지 않다. 이 코드가 KSIC(한국표준산업분류) 10차 대분류 19개와 같은 순서로
매겨진다는 점을 이용해 산업명을 매핑했다. 02번과 같은 면적비례 배분으로 종사자수를
합산한 뒤 업종별 비율을 계산한다.

```bash
python 04_industry_classification.py \
  --boundary-shp bnd_oa_31023_2025_2Q.shp \
  --emp-csv "31023_2023년_산업분류별(10차_대분류)_종사자수.csv" \
  --boundary pangyo_final.geojson \
  --label pangyo
```

## 참고 — 그 외 처리한 것들

위 4개로 분석의 핵심 로직은 거의 다 다루지만, 다음은 별도 스크립트 없이 1회성으로
처리한 부분이다(분량이 적어 스크립트화하지 않음).

용도지역 혼합도(LUM, 엔트로피 지수)는 `-Σ(p_i · ln p_i) / ln(n)` 공식을 주용도별 연면적
비율에 그대로 적용했고, n은 등장하는 용도 종류 수다. 도로망 밀도는 OpenStreetMap에서
받은 도로(`way[highway]`) 중 차도 분류(`motorway`~`unclassified`, 보행자·계단·자전거
제외)만 골라 분석 경계로 클립하고 길이를 합산한 뒤 면적(km²)으로 나눠 구했다. 버스정류장
밀도는 국토교통부 전국 버스정류장 위치정보(위도·경도)가 분석 경계 폴리곤 안에 포함되는지
(`Polygon.contains(Point)`)를 기준으로 필터링한 후 개수를 면적(km²)으로 나눴다. 누적
개발 타임라인은 건축물대장의 `사용승인일` 컬럼에서 연도만 추출하고, 건물 단위로 중복을
제거한 다음 연도별 신축 건수를 누적합으로 변환해서 만들었다.
