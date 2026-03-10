"""
mic_volume_tray.py
Windowsのマイク入力音量（設定値）をシステムトレイにリアルタイム表示するアプリ

必要パッケージ:
    uv add pycaw comtypes pystray pillow

使い方:
    uv run python mic_volume_tray.py
"""

import threading
import sys
import ctypes
from comtypes import CLSCTX_ALL, COMError
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, EDataFlow, ERole
from pycaw.callbacks import AudioEndpointVolumeCallback
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item


# ─── 設定 ───────────────────────────────────────────────
ICON_SIZE = 64          # アイコンサイズ (px)
POLL_INTERVAL = 0.5     # ポーリング間隔 (秒) ※コールバックが効かない場合の保険
BAR_COUNT = 5           # バーの本数
# ────────────────────────────────────────────────────────

# グローバル状態
tray_icon = None
current_volume = -1     # 0〜100
endpoint_volume = None
lock = threading.Lock()
stop_event = threading.Event()

# ゲインロック状態
gain_lock_enabled = False   # ロック機能の ON/OFF
gain_lock_target = None     # ロック先の音量 (0〜100), None=未設定


class VolumeCallback(AudioEndpointVolumeCallback):
    """音量変更コールバック: Windows が音量を変えたら即座に反映"""
    def OnNotify(self, pNotify):
        # pNotify.fMasterVolume は 0.0〜1.0
        new_vol = round(pNotify.fMasterVolume * 100)
        with lock:
            global current_volume
            current_volume = new_vol
        update_icon(new_vol)


def get_mic_endpoint_volume():
    """デフォルトの録音デバイス(マイク)の IAudioEndpointVolume を取得"""
    # pycaw の DeviceEnumerator 経由でデフォルト録音デバイスを取得
    devices = AudioUtilities.GetAllDevices()

    enumerator = AudioUtilities.GetDeviceEnumerator()
    # EDataFlow.eCapture=1, ERole.eMultimedia=1
    default_mic = enumerator.GetDefaultAudioEndpoint(1, 1)

    volume = default_mic.Activate(
        IAudioEndpointVolume._iid_,
        CLSCTX_ALL,
        None,
    )
    return volume.QueryInterface(IAudioEndpointVolume)


def get_current_mic_volume_pct():
    """現在のマイク入力音量を 0〜100 の整数で返す"""
    if endpoint_volume is None:
        return 0
    try:
        level = endpoint_volume.GetMasterVolumeLevelScalar()  # 0.0〜1.0
        return round(level * 100)
    except COMError:
        return 0


def make_icon(level_pct: int) -> Image.Image:
    """
    音量レベル(0〜100)に応じたアイコン画像を生成。
    上部に数字、下部にバーグラフを描画。
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── 数値テキスト（上部中央に大きく表示）──
    try:
        font_num = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font_num = ImageFont.load_default()

    text = str(level_pct)
    bbox = draw.textbbox((0, 0), text, font=font_num)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (ICON_SIZE - tw) // 2
    ty = 0
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font_num)

    # ── バーグラフ（下部）──
    bar_w = 8
    gap = 3
    total_w = BAR_COUNT * bar_w + (BAR_COUNT - 1) * gap
    start_x = (ICON_SIZE - total_w) // 2
    bar_area_top = th + 4
    bar_area_bottom = ICON_SIZE - 2
    max_h = bar_area_bottom - bar_area_top

    frac = level_pct / 100.0

    for i in range(BAR_COUNT):
        bar_h = int(max_h * (i + 1) / BAR_COUNT)
        x0 = start_x + i * (bar_w + gap)
        y0 = bar_area_bottom - bar_h
        x1 = x0 + bar_w
        y1 = bar_area_bottom

        threshold = (i + 1) / BAR_COUNT
        if frac >= threshold:
            # 音量に応じて色を変える: 緑→黄→赤
            if frac < 0.5:
                color = (50, 220, 80, 255)
            elif frac < 0.8:
                color = (230, 200, 30, 255)
            else:
                color = (230, 50, 50, 255)
        else:
            color = (80, 80, 80, 160)

        draw.rectangle([x0, y0, x1, y1], fill=color)

    return img


def update_icon(level_pct: int):
    """トレイアイコンを更新"""
    if tray_icon is None:
        return
    img = make_icon(level_pct)
    tray_icon.icon = img
    tray_icon.title = f"マイク入力音量: {level_pct}%"


def poller():
    """
    定期的に音量を確認するポーリングスレッド。
    コールバックで拾えないケース（デバイス切替等）の保険。
    ゲインロックが有効な場合、設定値と異なれば自動で戻す。
    """
    while not stop_event.is_set():
        try:
            vol = get_current_mic_volume_pct()
            with lock:
                global current_volume
                # ゲインロック: 有効かつターゲットと異なれば戻す
                if gain_lock_enabled and gain_lock_target is not None:
                    if vol != gain_lock_target:
                        set_mic_volume(gain_lock_target)
                        vol = gain_lock_target
                if vol != current_volume:
                    current_volume = vol
                    update_icon(vol)
        except Exception:
            pass
        stop_event.wait(POLL_INTERVAL)


def set_mic_volume(level_pct: int):
    """マイク入力音量を 0〜100 の整数で設定"""
    if endpoint_volume is None:
        return
    try:
        endpoint_volume.SetMasterVolumeLevelScalar(level_pct / 100.0, None)
    except COMError:
        pass


def _make_gain_setter(level: int):
    """指定レベルで音量を設定するコールバックを返す（ロックターゲットも更新）"""
    def setter(icon, item_obj):
        global gain_lock_target
        set_mic_volume(level)
        with lock:
            gain_lock_target = level
    return setter


def _gain_checked(level: int):
    """現在の音量に最も近いメニュー項目にチェックを付ける"""
    def checked(item_obj):
        with lock:
            vol = current_volume
        # 最も近い10刻みの値と比較
        nearest = round(vol / 10) * 10
        return nearest == level
    return checked


def build_menu():
    """トレイのコンテキストメニュー"""
    def quit_app(icon, item_obj):
        stop_event.set()
        icon.stop()
        sys.exit(0)

    # ゲイン設定サブメニュー (0, 10, 20, ..., 100)
    gain_items = []
    for level in range(0, 101, 10):
        gain_items.append(
            item(
                f"{level}%",
                _make_gain_setter(level),
                checked=_gain_checked(level),
                radio=True,
            )
        )

    # ゲインロック ON/OFF トグル
    def toggle_gain_lock(icon, item_obj):
        global gain_lock_enabled
        with lock:
            gain_lock_enabled = not gain_lock_enabled

    def is_gain_lock_enabled(item_obj):
        return gain_lock_enabled

    return pystray.Menu(
        item("ゲイン設定", pystray.Menu(*gain_items)),
        item("ゲインロック", toggle_gain_lock, checked=is_gain_lock_enabled),
        pystray.Menu.SEPARATOR,
        item("終了", quit_app),
    )


def main():
    global tray_icon, endpoint_volume, current_volume

    # COM 初期化は pycaw 内部で自動的に行われる
    endpoint_volume = get_mic_endpoint_volume()

    # コールバック登録
    callback = VolumeCallback()
    endpoint_volume.RegisterControlChangeNotify(callback)

    # 初期値取得
    current_volume = get_current_mic_volume_pct()
    initial_icon = make_icon(current_volume)

    tray_icon = pystray.Icon(
        name="MicVolume",
        icon=initial_icon,
        title=f"マイク入力音量: {current_volume}%",
        menu=build_menu(),
    )

    # ポーリングスレッド開始
    poll_thread = threading.Thread(target=poller, daemon=True)
    poll_thread.start()

    print(f"マイク入力音量: {current_volume}%  — トレイに表示中（右クリックで終了）")
    tray_icon.run()


if __name__ == "__main__":
    main()
