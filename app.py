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

# ========== 系統參數 ==========
map_center = [25.04, 121.56]  # 台北市中心

# ========== 關閉雙擊放大 ==========
class DisableDoubleClickZoom(MacroElement):
    def __init__(self):
        super().__init__()
        self._template = Template("""
            {% macro script(this, kwargs) %}
                {{this._parent.get_name()}}.doubleClickZoom.disable();
            {% endmacro %}
        """)

# ========== 讀取圖 ==========
@st.cache_resource
def load_graph():
    pkl_path = r"data/Tai_Road_濃度_最大連通版.pkl"
    with open(pkl_path, "rb") as f:
        G = pickle.load(f)

    transformer = Transformer.from_crs("epsg:3826", "epsg:4326", always_xy=True)
    mapping = {}
    for node in list(G.nodes):
        lon, lat = transformer.transform(node[0], node[1])
        mapping[(lat, lon)] = node
        G.nodes[node]["latlon"] = (lat, lon)

    G.graph['latlon_nodes'] = list(mapping.keys())
    G.graph['node_lookup'] = mapping
    return G

# ====== Geocoding ======
def geocode(address):
    api_key = "AIzaSyDnbTu8PgUkue5A9uO5aJa3lHZuNUwj6z0"
    full_address = "台灣 " + address
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": full_address, "language": "zh-TW", "key": api_key}
    try:
        response = requests.get(url, params=params).json()
        if response["status"] == "OK":
            location = response["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
        else:
            st.warning(f"⚠️ Google 回應：{response['status']} - {response.get('error_message', '無錯誤訊息')}")
            return None
    except Exception as e:
        st.error(f"地址查詢失敗: {e}")
        return None

# ====== Reverse Geocoding ======
def reverse_geocode(lat, lon):
    api_key = "AIzaSyDnbTu8PgUkue5A9uO5aJa3lHZuNUwj6z0"
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lon}", "language": "zh-TW", "key": api_key}
    try:
        response = requests.get(url, params=params).json()
        if response["status"] == "OK":
            return response["results"][0]["formatted_address"]
        else:
            return ""
    except Exception as e:
        return ""

# ========== 找最近節點 ==========
def find_nearest_node(G, lat, lon, max_dist=0.01):
    kdtree = KDTree(G.graph['latlon_nodes'])
    dist, idx = kdtree.query((lat, lon))
    if dist > max_dist:
        return None
    latlon = G.graph['latlon_nodes'][idx]
    return G.graph['node_lookup'][latlon]

# ========== 路徑計算 ==========
def compute_path(G, start_node, end_node, weight):
    try:
        path = nx.shortest_path(G, start_node, end_node, weight=lambda u, v, d: d.get("attr_dict", {}).get(weight, 0))
    except nx.NetworkXNoPath:
        return None, 0, 0

    total = 0
    exposure = 0
    for u, v in zip(path[:-1], path[1:]):
        edge_data = G.get_edge_data(u, v)
        if edge_data and "attr_dict" in edge_data:
            attrs = edge_data["attr_dict"]
            total += attrs.get("length", 0)
            exposure += attrs.get("exposure", 0)
        else:
            for d in edge_data.values():
                attrs = d.get("attr_dict", {})
                total += attrs.get("length", 0)
                exposure += attrs.get("exposure", 0)

    return path, total, exposure

### ========== Streamlit 介面 ========== ###
st.set_page_config(layout="wide")

# 初始化狀態
if "transport_mode" not in st.session_state:
    st.session_state.transport_mode = "機車"
if "points" not in st.session_state:
    st.session_state.points = []
if "nodes" not in st.session_state:
    st.session_state.nodes = []
if "disable_inputs" not in st.session_state:
    st.session_state.disable_inputs = False
if "show_pm25_layer" not in st.session_state:
    st.session_state.show_pm25_layer = False

G = load_graph()
col1, col2 = st.columns([5, 7])

with col1:
    st.title("Geo-AI 路徑好空氣")

    start_address = st.text_input("起點地址", value=st.session_state.get("start_address", ""), disabled=st.session_state.disable_inputs)
    end_address = st.text_input("終點地址", value=st.session_state.get("end_address", ""), disabled=st.session_state.disable_inputs)

    if st.button("🔴 確定終點"):
        if start_address.strip() and end_address.strip():
            start_result = geocode(start_address)
            end_result = geocode(end_address)

            if start_result and end_result:
                s_lat, s_lon = start_result
                e_lat, e_lon = end_result
                s_node = find_nearest_node(G, s_lat, s_lon)
                e_node = find_nearest_node(G, e_lat, e_lon)

                if s_node and e_node:
                    st.session_state.points = [G.nodes[s_node]["latlon"], G.nodes[e_node]["latlon"]]
                    st.session_state.nodes = [s_node, e_node]
                    st.session_state.start_address = start_address
                    st.session_state.end_address = end_address
                    st.session_state.disable_inputs = True
                    st.rerun()
                else:
                    st.warning("地址與路網距離過遠")
            else:
                st.warning("地址無法轉換為座標")
        else:
            st.warning("請輸入起點與終點地址")

    if st.button("🔃 重新選擇"):
        st.session_state.points = []
        st.session_state.nodes = []
        st.session_state.disable_inputs = False
        st.rerun()

    st.write("目前交通方式：", st.session_state.transport_mode)
    st.button("機車", on_click=lambda: st.session_state.update(transport_mode="機車"))
    st.button("單車", on_click=lambda: st.session_state.update(transport_mode="單車"))
    st.button("步行", on_click=lambda: st.session_state.update(transport_mode="步行"))

    if len(st.session_state.nodes) == 2:
        SPEED = {"機車": 50, "單車": 18, "步行": 5}[st.session_state.transport_mode]
        path1, dist1, expo1 = compute_path(G, *st.session_state.nodes, "length")
        path2, dist2, expo2 = compute_path(G, *st.session_state.nodes, "exposure")
        df = pd.DataFrame({
            "類型": ["最短路徑", "最低暴露"],
            "距離(km)": [round(dist1/1000, 2), round(dist2/1000, 2)],
            "時間(min)": [round(dist1/1000/SPEED*60, 2), round(dist2/1000/SPEED*60, 2)],
            "每分鐘暴露量": [round(expo1/(dist1/1000/SPEED*60), 2) if dist1 else 0,
                         round(expo2/(dist2/1000/SPEED*60), 2) if dist2 else 0]
        })
        st.dataframe(df)

with col2:
    m = folium.Map(location=map_center, zoom_start=13, control_scale=True)
    m.add_child(DisableDoubleClickZoom())

    for i, pt in enumerate(st.session_state.points):
        label = "起點" if i == 0 else "終點"
        color = "green" if i == 0 else "red"
        folium.Marker(location=pt, tooltip=label, icon=folium.Icon(color=color)).add_to(m)

    if len(st.session_state.nodes) == 2:
        for path, color, label in [
            (compute_path(G, *st.session_state.nodes, "length")[0], "blue", "最短路徑"),
            (compute_path(G, *st.session_state.nodes, "exposure")[0], "orange", "最低暴露路徑")
        ]:
            if path:
                for u, v in zip(path[:-1], path[1:]):
                    edge_data = G.get_edge_data(u, v)
                    for d in edge_data.values():
                        geom = d.get("attr_dict", {}).get("geometry")
                        if geom:
                            coords = [(lat, lon) for lon, lat in geom.coords]
                            folium.PolyLine(coords, color=color, weight=4, tooltip=label).add_to(m)
                        else:
                            pt1 = G.nodes[u]["latlon"]
                            pt2 = G.nodes[v]["latlon"]
                            folium.PolyLine([pt1, pt2], color=color, weight=4, tooltip=label).add_to(m)

    if st.session_state.show_pm25_layer:
        from folium.raster_layers import ImageOverlay

        png_path = r"data/PM25_大台北2.png"
        left_twd97 = 278422.218791
        right_twd97 = 351672.218791
        bottom_twd97 = 2729604.773102
        top_twd97 = 2799454.773102

        transformer = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)
        left_lon, bottom_lat = transformer.transform(left_twd97, bottom_twd97)
        right_lon, top_lat = transformer.transform(right_twd97, top_twd97)

        with open(png_path, "rb") as f:
            png_base64 = base64.b64encode(f.read()).decode("utf-8")
        image_url = f"data:image/png;base64,{png_base64}"
        bounds = [[bottom_lat, left_lon], [top_lat, right_lon]]

        ImageOverlay(image=image_url, bounds=bounds, opacity=0.5).add_to(m)

    if not st.session_state.disable_inputs:
        st_data = st_folium(m, width=700, height=600)
        if st_data and st_data.get("last_clicked"):
            st.warning("地圖點擊功能已停用，請透過地址輸入進行解算")

