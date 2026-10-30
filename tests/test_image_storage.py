import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage

from models import Product, User
from utils import ImageStorageError, ImageUploadError, delete_image, save_image


class ImageStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config.update(
            UPLOAD_FOLDER=self.temp_dir.name,
            IMAGE_STORAGE_BACKEND="local",
            CLOUDFLARE_R2_ACCOUNT_ID="account-id",
            CLOUDFLARE_R2_ACCESS_KEY_ID="access-key",
            CLOUDFLARE_R2_SECRET_ACCESS_KEY="secret-key",
            CLOUDFLARE_R2_BUCKET="marketplace-images",
            CLOUDFLARE_R2_PUBLIC_URL="https://images.example.test",
        )
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        self.context.pop()
        self.temp_dir.cleanup()

    @staticmethod
    def _upload(filename="photo.png", mode="RGB"):
        source = Image.new(mode, (64, 48), (200, 30, 80))
        data = io.BytesIO()
        source.save(data, format="PNG")
        data.seek(0)
        return FileStorage(stream=data, filename=filename)

    def test_local_upload_is_compressed_and_saved_as_webp(self):
        path = save_image(self._upload())
        output = Path(self.temp_dir.name) / Path(path).name

        self.assertTrue(path.startswith("uploads/"))
        self.assertTrue(path.endswith(".webp"))
        self.assertTrue(output.is_file())
        self.assertEqual(output.read_bytes()[:4], b"RIFF")
        with Image.open(output) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (64, 48))
        self.assertLess(output.stat().st_size, 64 * 48 * 3)

    def test_r2_image_references_render_as_public_urls(self):
        image_path = "r2:uploads/example photo.webp"

        product = Product(image_path=image_path)
        user = User(avatar_path=image_path)

        self.assertEqual(
            product.image_url,
            "https://images.example.test/uploads/example%20photo.webp",
        )
        self.assertEqual(product.image_external_url, product.image_url)
        self.assertEqual(user.avatar_url, product.image_url)

    def test_r2_upload_stores_webp_and_returns_remote_key(self):
        self.app.config["IMAGE_STORAGE_BACKEND"] = "r2"
        client = Mock()
        with patch("utils._r2_client", return_value=client):
            image_path = save_image(self._upload())

        self.assertTrue(image_path.startswith("r2:uploads/"))
        self.assertTrue(image_path.endswith(".webp"))
        request = client.put_object.call_args.kwargs
        self.assertEqual(request["Bucket"], "marketplace-images")
        self.assertEqual(request["Key"], image_path[3:])
        self.assertEqual(request["ContentType"], "image/webp")
        self.assertEqual(request["Body"][:4], b"RIFF")

    def test_r2_upload_requires_complete_configuration(self):
        self.app.config["IMAGE_STORAGE_BACKEND"] = "r2"
        self.app.config["CLOUDFLARE_R2_PUBLIC_URL"] = ""

        with self.assertRaisesRegex(ImageStorageError, "CLOUDFLARE_R2_PUBLIC_URL"):
            save_image(self._upload())

    def test_invalid_image_is_reported(self):
        upload = FileStorage(stream=io.BytesIO(b"not an image"), filename="bad.png")

        with self.assertRaises(ImageUploadError):
            save_image(upload)

    def test_r2_delete_removes_object_by_key(self):
        self.app.config["IMAGE_STORAGE_BACKEND"] = "r2"
        client = Mock()
        with patch("utils._r2_client", return_value=client):
            delete_image("r2:uploads/image.webp")

        client.delete_object.assert_called_once_with(
            Bucket="marketplace-images",
            Key="uploads/image.webp",
        )


if __name__ == "__main__":
    unittest.main()
