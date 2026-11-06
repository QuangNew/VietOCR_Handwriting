import unittest
from PIL import Image
from desktop.shape_crop import crop_shape, outline, rotate_points
from desktop.image_modes import black_white


class ShapeCropTests(unittest.TestCase):
    def setUp(self):
        self.image=Image.new('RGB',(100,80))
        self.image.putdata([(x*2,y*3,30) for y in range(80) for x in range(100)])

    def test_rectangle_retains_native_pixels_and_rotated_region_is_straightened(self):
        points=outline((20,20,60,40))
        crop=crop_shape(self.image,points)
        self.assertEqual(crop.size,(40,20))
        self.assertEqual(crop.getpixel((10,10)),self.image.getpixel((30,30)))
        rotated=crop_shape(self.image,points,90)
        expected=self.image.getpixel((50,10))
        for a,b in zip(rotated.getpixel((1,1)),self.image.getpixel((49,11))): self.assertLessEqual(abs(a-b),3)
        self.assertEqual(rotated.size,(40,20))
        self.assertEqual(rotate_points(points,90)[0],(50.0,10.0))

    def test_ellipse_and_concave_freehand_keep_white_background(self):
        ellipse=crop_shape(self.image,outline((10,10,90,70),'ellipse'))
        self.assertEqual(ellipse.getpixel((0,0)),(255,255,255))
        self.assertEqual(ellipse.getpixel((40,30)),self.image.getpixel((50,40)))
        points=[(10,10),(80,10),(80,30),(30,30),(30,70),(10,70)]
        crop=crop_shape(self.image,points)
        self.assertEqual(crop.getpixel((50,40)),(255,255,255))
        self.assertEqual(crop.getpixel((10,40)),self.image.getpixel((20,50)))

    def test_invalid_region_rejected_and_original_not_mutated(self):
        before=self.image.tobytes()
        for points,angle in [([(0,0),(1,1)],0), ([(0,0),(20,20),(40,40)],0),(outline((0,0,20,20)),float('nan'))]:
            with self.assertRaises(ValueError):crop_shape(self.image,points,angle)
        black_white(self.image)
        self.assertEqual(before,self.image.tobytes())

    def test_black_white_keeps_resolution_and_ink_on_uneven_background(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(180,80),'#aaaaaa')
        ImageDraw.Draw(image).line((20,40,160,40),fill='#801010',width=3)
        result=black_white(image)
        self.assertEqual(result.size,image.size)
        self.assertEqual(result.getpixel((60,40)),(0,0,0))
        self.assertEqual(result.getpixel((60,10)),(255,255,255))
