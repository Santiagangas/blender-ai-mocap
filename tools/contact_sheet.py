"""Build a labelled contact sheet from video frames (dev helper).

    python tools/contact_sheet.py video.mp4 out.png 0,30,60,95,125,150
"""
import sys

import cv2
import numpy as np

video, out, frames = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
cap = cv2.VideoCapture(video)
tiles = []
for f in frames:
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok, img = cap.read()
    if not ok:
        continue
    scale = 320 / img.shape[0]
    img = cv2.resize(img, None, fx=scale, fy=scale)
    cv2.putText(img, f"f{f + 1}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    tiles.append(img)
cv2.imwrite(out, np.hstack(tiles))
print("wrote", out)
