import io
import os
import traceback
import numpy as np
import cv2
from flask import Flask, request, Response, send_file, jsonify
from rembg import new_session, remove
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')

# Загружаем модель один раз при старте
session = new_session(model_name="u2netp")


def restore_internal_holes(pil_image, original_image):
    result_arr = np.array(pil_image)
    original_arr = np.array(original_image.convert('RGBA'))
    if result_arr.shape[2] < 4:
        return pil_image
    h, w = result_arr.shape[:2]
    result_alpha = result_arr[:, :, 3]
    transparent_mask = (result_alpha < 128).astype(np.uint8)
    if transparent_mask.sum() == 0:
        return pil_image
    orig_alpha = original_arr[:, :, 3]
    original_object = (orig_alpha > 128).astype(np.uint8)
    interior_holes = transparent_mask & original_object
    if interior_holes.sum() == 0:
        return pil_image
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(interior_holes, connectivity=8)
    result = result_arr.copy()
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        hole_mask = (labels == i)
        orig_brightness = original_arr[hole_mask, :3].mean()
        if area < 1 or area > h * w * 0.3:
            continue
        if orig_brightness > 50:
            result[hole_mask, :3] = original_arr[hole_mask, :3]
            result[hole_mask, 3] = 255
    return Image.fromarray(result, 'RGBA')


def clean_mask_gaps(pil_image, gap_size=2):
    arr = np.array(pil_image)
    if arr.shape[2] < 4:
        return pil_image
    alpha = arr[:, :, 3]
    opaque = (alpha > 128).astype(np.uint8)
    kernel = np.ones((gap_size * 2 + 1, gap_size * 2 + 1), np.uint8)
    closed = cv2.morphologyEx(opaque, cv2.MORPH_CLOSE, kernel)
    filled = closed - opaque
    if filled.sum() == 0:
        return pil_image
    bg_mask = (opaque == 0).astype(np.uint8)
    h, w = bg_mask.shape
    start = None
    for x in range(w):
        if bg_mask[0, x] == 1: start = (x, 0); break
        if bg_mask[h-1, x] == 1: start = (x, h-1); break
    if start is None:
        for y in range(h):
            if bg_mask[y, 0] == 1: start = (0, y); break
            if bg_mask[y, w-1] == 1: start = (w-1, y); break
    if start is None:
        return pil_image
    exterior_bg = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(bg_mask.copy(), exterior_bg, start, 1, loDiff=0, upDiff=0)
    exterior_bg = exterior_bg[1:-1, 1:-1]
    result = arr.copy()
    to_fill = filled & exterior_bg
    result[to_fill > 0, 3] = 0
    return Image.fromarray(result, 'RGBA')


def remove_color_fringe(pil_image):
    arr = np.array(pil_image)
    if arr.shape[2] < 4:
        return pil_image
    alpha = arr[:, :, 3]
    h, w = alpha.shape
    object_mask = (alpha > 128).astype(np.uint8)
    transparent_mask = (alpha < 128).astype(np.uint8)
    exterior_bg = np.zeros((h + 2, w + 2), np.uint8)
    start = None
    for x in range(w):
        if transparent_mask[0, x] == 1: start = (x, 0); break
        if transparent_mask[h-1, x] == 1: start = (x, h-1); break
    if start is None:
        for y in range(h):
            if transparent_mask[y, 0] == 1: start = (0, y); break
            if transparent_mask[y, w-1] == 1: start = (w-1, y); break
    if start is None:
        return pil_image
    temp = transparent_mask.copy()
    cv2.floodFill(temp, exterior_bg, start, 1, loDiff=0, upDiff=0)
    exterior_bg = exterior_bg[1:-1, 1:-1]
    bg_zone = exterior_bg > 0
    if bg_zone.sum() == 0:
        return pil_image
    bg_color = arr[bg_zone, :3].mean(axis=0)
    halo_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    expanded = cv2.dilate(object_mask, halo_kernel, iterations=1)
    exterior_halo = (expanded - object_mask) & exterior_bg
    if exterior_halo.sum() > 0:
        arr[exterior_halo > 0, :3] = bg_color
        arr[exterior_halo > 0, 3] = 0
    semi_transparent = (alpha > 0) & (alpha <= 128)
    if semi_transparent.sum() > 0:
        st_mask = semi_transparent.astype(np.uint8)
        st_near_bg = st_mask & exterior_bg
        if st_near_bg.sum() > 0:
            arr[st_near_bg > 0, :3] = bg_color
            arr[st_near_bg > 0, 3] = 0
        edge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        obj_edges = object_mask - cv2.erode(object_mask, edge_kernel)
        if obj_edges.sum() > 0:
            edge_pixels = obj_edges > 0
            edge_colors = arr[edge_pixels, :3]
            dist = np.sqrt(np.sum((edge_colors - bg_color) ** 2, axis=1))
            fringe_pixels = dist < 30
            if fringe_pixels.sum() > 0:
                edge_indices = np.where(edge_pixels)[0]
                fringe_indices = edge_indices[fringe_pixels]
                y_coords, x_coords = np.where(obj_edges)
                arr[y_coords[fringe_indices], x_coords[fringe_indices], 3] = 0
    return Image.fromarray(arr, 'RGBA')


@app.route('/')
def index():
    return send_file(os.path.join(BASE_DIR, 'index.html'))


@app.route('/remove-bg', methods=['POST'])
def remove_background():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    try:
        file = request.files['image']
        image_data = file.read()
        input_image = Image.open(io.BytesIO(image_data))
        original_for_restore = input_image.copy()
        if input_image.mode == 'RGBA':
            input_image = input_image.convert('RGB')

        output_image = remove(input_image, session=session)

        output_image = remove_color_fringe(output_image)
        output_image = restore_internal_holes(output_image, original_for_restore)
        output_image = clean_mask_gaps(output_image, gap_size=2)

        # Освобождаем память
        del input_image
        del original_for_restore
        import gc
        gc.collect()
        
        img_io = io.BytesIO()
        output_image.save(img_io, 'PNG')
        img_data = img_io.getvalue()
        response = Response(img_data, mimetype='image/png')
        response.headers['X-Original-Filename'] = file.filename or 'image'
        return response
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Открой в браузере: http://localhost:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)
