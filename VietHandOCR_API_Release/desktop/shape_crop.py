"""Crop in native pixels, with a rotatable polygon and a white OCR background."""
import math
from PIL import Image, ImageDraw


def outline(box, shape='rectangle'):
    l,t,r,b=box
    if shape=='ellipse':
        cx,cy=(l+r)/2,(t+b)/2
        return [(cx+(r-l)/2*math.cos(i*math.tau/96),cy+(b-t)/2*math.sin(i*math.tau/96)) for i in range(96)]
    return [(l,t),(r,t),(r,b),(l,b)]


def rotate_points(points, angle):
    if not points: return []
    cx=(min(p[0] for p in points)+max(p[0] for p in points))/2
    cy=(min(p[1] for p in points)+max(p[1] for p in points))/2
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    return [(cx+c*(x-cx)-s*(y-cy),cy+s*(x-cx)+c*(y-cy)) for x,y in points]


def crop_shape(image, points, angle=0):
    if not 3<=len(points)<=4096 or not math.isfinite(angle) or abs(angle)>180:
        raise ValueError('Vẽ một vùng kín có ít nhất 3 điểm rồi crop.')
    if any(not math.isfinite(v) or abs(v)>2*max(image.size) for p in points for v in p):
        raise ValueError('Tọa độ crop không hợp lệ.')
    area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1])))/2
    l,t=math.floor(min(p[0] for p in points)),math.floor(min(p[1] for p in points))
    r,b=math.ceil(max(p[0] for p in points)),math.ceil(max(p[1] for p in points))
    w,h=r-l,b-t
    if area<2 or w<2 or h<2 or w*h>12_000_000: raise ValueError('Vùng crop rỗng hoặc vượt 12 MP.')
    cx,cy=(min(p[0] for p in points)+max(p[0] for p in points))/2,(min(p[1] for p in points)+max(p[1] for p in points))/2
    c,s=math.cos(math.radians(angle)),math.sin(math.radians(angle))
    # Inverse mapping rotates the selection over the image, then straightens
    # the selected content in the result. One resample, no source enlargement.
    result=image.convert('RGB').transform((w,h),Image.Transform.AFFINE,
        (c,-s,cx+c*(l-cx)-s*(t-cy),s,c,cy+s*(l-cx)+c*(t-cy)),
        Image.Resampling.BICUBIC,fillcolor='white')
    mask=Image.new('L',(w*2,h*2),0)
    ImageDraw.Draw(mask).polygon([((x-l)*2,(y-t)*2) for x,y in points],fill=255)
    mask=mask.resize((w,h),Image.Resampling.LANCZOS)
    return Image.composite(result,Image.new('RGB',(w,h),'white'),mask)
