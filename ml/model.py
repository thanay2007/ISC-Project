import cv2
import numpy as np
import torch
from torch import nn

from ml.scripts.prepare_dataset import letterbox


def tensor_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    residual = (gray - cv2.GaussianBlur(gray, (5, 5), .85)) * 3
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    return torch.from_numpy(np.concatenate(((rgb.transpose(2, 0, 1) - .6) * 2, residual[None])))


def block(inputs, outputs):
    return nn.Sequential(nn.Conv2d(inputs, outputs, 3, padding=1, bias=False),
                         nn.BatchNorm2d(outputs), nn.ReLU(inplace=True),
                         nn.Conv2d(outputs, outputs, 3, padding=1, bias=False),
                         nn.BatchNorm2d(outputs), nn.ReLU(inplace=True))


class BalancedForgeryUNet(nn.Module):
    def __init__(self, mask_score_weight=0., mask_score_divisor=160):
        super().__init__()
        fine, coarse, bottleneck, evidence = 12, 24, 48, 4
        self.enc1 = block(4, fine)
        self.enc2 = block(fine, coarse)
        self.bridge = block(coarse, bottleneck)
        self.dec2 = block(bottleneck + coarse, coarse)
        self.dec1 = block(coarse + fine, fine)
        self.output = nn.Conv2d(fine, 1, 1)
        self.pool = nn.MaxPool2d(2)
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)
        self.evidence = nn.Conv2d(fine, evidence, 1)
        pooled_channels = 2 * (bottleneck + evidence) + 1
        self.classifier = nn.Sequential(nn.Linear(pooled_channels, 48), nn.ReLU(), nn.Dropout(.15), nn.Linear(48, 1))
        self.mask_score_weight = mask_score_weight
        self.mask_score_divisor = mask_score_divisor

    def features(self, image):
        level1 = self.enc1(image)
        level2 = self.enc2(self.pool(level1))
        middle = self.bridge(self.pool(level2))
        high = self.dec2(torch.cat((self.up(middle), level2), dim=1))
        return self.dec1(torch.cat((self.up(high), level1), dim=1)), middle

    def forward(self, image, return_features=False):
        detail, middle = self.features(image)
        mask = self.output(detail)
        local = self.evidence(detail).flatten(2)
        strongest = local.topk(max(1, local.shape[-1] // 160), dim=-1).values.mean(dim=-1)
        pooled = torch.cat((middle.mean((2, 3)), middle.amax((2, 3)), local.mean(-1), strongest,
                            image_logit(mask).detach().unsqueeze(1)), dim=1)
        page = self.classifier(pooled).squeeze(1)
        if self.mask_score_weight:
            page = torch.lerp(page.float(), image_logit(mask.float(), self.mask_score_divisor), self.mask_score_weight)
        return (mask, page, pooled) if return_features else (mask, page)


def model_for(config):
    if config.get("architecture") != "balanced-unet":
        raise ValueError("Expected a Balanced U-Net checkpoint.")
    return BalancedForgeryUNet(config.get("mask_score_weight", 0.), config.get("mask_score_divisor", 160))


def image_logit(mask_logits, divisor=160):
    pixels = mask_logits.flatten(1)
    count = max(1, pixels.shape[1] // divisor)
    return pixels.topk(count, dim=1).values.mean(dim=1)


def predict_map(model, image, size, return_features=False):
    page, (x, y, w, h) = letterbox(image, size)
    with torch.inference_mode():
        prediction = model(tensor_image(page).unsqueeze(0), return_features=return_features)
        logits, classification = prediction[:2]
        score = classification.sigmoid().item()
        heatmap = torch.sigmoid(logits)[0, 0, y:y+h, x:x+w].numpy()
    if return_features:
        return score, heatmap, prediction[2][0].numpy(), page[y:y+h, x:x+w]
    return score, heatmap
