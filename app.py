# =========================== #
#  app_update.py — 修改說明：
#  1. 移除「確定起點」按鈕
#  2. 按「確定終點」時同時使用起點與終點解算路徑
#  3. 解算後鎖定起終點地址與地圖點選
# =========================== #

import streamlit as st
import folium
import pickle
import requests
import networkx as nx
import pandas as pd
from streamlit_folium import st_folium
from shapely.geometry import LineString
from scipy.spatial import KDTree
from branca.element import MacroElement
from jinja2 import Template
from pyproj import Transformer
import base64

st.set_page_config(layout="wide")

# ========== 關閉雙擊放大 ==========
class DisableDoubleClickZoom(MacroElement):
    def __init__(self):
        super().__init__()
        self._template = Template("""
            {% macro script(this, kwargs) %}
                {{this._parent.get_name()}}.doubleClickZoom.disable();
            {% endmacro %}
        """)

# ========== 資料初始化 ==========
@st.cache_resource
def load_graph():
    with open("data/Tai_Road_濃度_最大連通版.pkl", "rb") as f:
        G = pickle.load(f)
    transformer = Transformer.from_crs("epsg:3826", "epsg:4326", always_xy=True)
    mapping = {}
    for node in list(G.nodes):
        lon, lat = transformer.transform(node[0], node[1])
        mapping[(lat, lon)] = node
        G.nodes[node]["latlon"] = (lat, lon)
    G.graph["latlon_nodes"] = list(mapping.keys())
    G.graph["node_lookup"] = mapping
    return G

def geocode(address):
    api_key = "AIzaSyDnbTu8PgUkue5A9uO5aJa3lHZuNUwj6z0"
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": "台灣 " + address, "language": "zh-TW", "key": api_key}
    try:
        response = requests.get(url, params=params).json()
        if response["status"] == "OK":
            loc = response["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except: pass
    return None

def find_nearest_node(G, lat, lon, max_dist=0.01):
    kdtree = KDTree(G.graph['latlon_nodes'])
    dist, idx = kdtree.query((lat, lon))
    if dist > max_dist:
        return None
    latlon = G.graph['latlon_nodes'][idx]
    return G.graph['node_lookup'][latlon]

def compute_path(G, start_node, end_node, weight):
    try:
        path = nx.shortest_path(G, start_node, end_node, weight=lambda u,v,d: d.get("attr_dict", {}).get(weight, 0))
    except nx.NetworkXNoPath:
        return None, 0, 0
    total = exposure = 0
    for u, v in zip(path[:-1], path[1:]):
        edge_data = G.get_edge_data(u, v)
        if edge_data:
            for d in edge_data.values():
                attrs = d.get("attr_dict", {})
                total += attrs.get("length", 0)
                exposure += attrs.get("exposure", 0)
    return path, total, exposure

# ========== 初始化 ==========
G = load_graph()
if "points" not in st.session_state: st.session_state.points = []
if "nodes" not in st.session_state: st.session_state.nodes = []
if "locked" not in st.session_state: st.session_state.locked = False

# ========== 使用者輸入 ==========
st.title("Geo-AI 路徑好空氣")

col1, col2 = st.columns(2)

with col1:
    start = st.text_input("起點地址", disabled=st.session_state.locked)
    end = st.text_input("終點地址", disabled=st.session_state.locked)
    if st.button("🔴 確定終點", disabled=st.session_state.locked):
        if start.strip() and end.strip():
            s_coord = geocode(start)
            e_coord = geocode(end)
            if s_coord and e_coord:
                s_node = find_nearest_node(G, *s_coord)
                e_node = find_nearest_node(G, *e_coord)
                if s_node and e_node:
                    st.session_state.points = [G.nodes[s_node]["latlon"], G.nodes[e_node]["latlon"]]
                    st.session_state.nodes = [s_node, e_node]
                    st.session_state.locked = True
                    st.rerun()
                else:
                    st.warning("⚠️ 任一端離路網太遠")
            else:
                st.warning("⚠️ Google 地理編碼失敗")
        else:
            st.warning("請完整輸入地址")

with col2:
    m = folium.Map(location=[25.04, 121.56], zoom_start=13)
    m.add_child(DisableDoubleClickZoom())

    for i, pt in enumerate(st.session_state.points):
        label = "起點" if i == 0 else "終點"
        color = "green" if i == 0 else "red"
        folium.Marker(location=pt, tooltip=label, icon=folium.Icon(color=color)).add_to(m)

    if len(st.session_state.nodes) == 2:
        for path, color in [
            (compute_path(G, *st.session_state.nodes, "length")[0], "blue"),
            (compute_path(G, *st.session_state.nodes, "exposure")[0], "orange")
        ]:
            if path:
                for u, v in zip(path[:-1], path[1:]):
                    data = G.get_edge_data(u, v)
                    for d in data.values():
                        geom = d.get("attr_dict", {}).get("geometry")
                        if geom:
                            coords = [(lat, lon) for lon, lat in geom.coords]
                            folium.PolyLine(coords, color=color, weight=4).add_to(m)
    st_data = st_folium(m, width=700, height=600)