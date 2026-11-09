import cv2
import numpy as np
import torch
from torch import nn

from ml.scripts.prepare_dataset import letterbox


def tensor_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    residual = (gray - cv2.GaussianBlur(gray, (5, 5), .85)) * 3
    return torch.from_numpy(np.stack([(gray - .6) * 2, residual]))


def block(inputs, outputs):
    return nn.Sequential(nn.Conv2d(inputs, outputs, 3, padding=1, bias=False),
                         nn.BatchNorm2d(outputs), nn.ReLU(inplace=True),
                         nn.Conv2d(outputs, outputs, 3, padding=1, bias=False),
                         nn.BatchNorm2d(outputs), nn.ReLU(inplace=True))


class ForgeryUNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.enc1 = block(2, 8)
        self.enc2 = block(8, 16)
        self.bridge = block(16, 24)
        self.dec2 = block(40, 16)
        self.dec1 = block(24, 8)
        self.output = nn.Conv2d(8, 1, 1)
        self.pool = nn.MaxPool2d(2)
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)

    def forward(self, image):
        level1 = self.enc1(image)
        level2 = self.enc2(self.pool(level1))
        middle = self.bridge(self.pool(level2))
        high = self.dec2(torch.cat((self.up(middle), level2), dim=1))
        return self.output(self.dec1(torch.cat((self.up(high), level1), dim=1)))


def image_logit(mask_logits):
    pixels = mask_logits.flatten(1)
    count = max(1, pixels.shape[1] // 160)
    return pixels.topk(count, dim=1).values.mean(dim=1)


def predict_map(model, image, size):
    page, (x, y, w, h) = letterbox(image, size)
    with torch.inference_mode():
        logits = model(tensor_image(page).unsqueeze(0))
        score = torch.sigmoid(image_logit(logits)).item()
        heatmap = torch.sigmoid(logits)[0, 0, y:y+h, x:x+w].numpy()
    return score, heatmap
