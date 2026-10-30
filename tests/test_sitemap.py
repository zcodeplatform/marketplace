import unittest
from datetime import datetime, timezone
from decimal import Decimal
from xml.etree import ElementTree

from app import create_app
from extensions import db
from models import Product, STATUS_ACTIVE, STATUS_SOLD, User


class SitemapTestConfig:
    SECRET_KEY = "sitemap-test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    ADMIN_EMAILS = ""
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    PRODUCT_VIEW_COOKIE_NAME = "marketplace_viewer"
    PRODUCT_VIEW_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60
    UPLOAD_FOLDER = ""


class SitemapTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(SitemapTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.seller = User()
        self.seller.name = "Seller"
        self.seller.email = "seller@example.test"
        db.session.add(self.seller)
        db.session.flush()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _add_product(self, slug, status=STATUS_ACTIVE):
        product = Product()
        product.slug = slug
        product.title = slug
        product.description = ""
        product.price = Decimal("10.00")
        product.category = "Other"
        product.status = status
        product.seller_id = self.seller.id
        db.session.add(product)
        db.session.flush()
        return product

    def test_sitemap_returns_xml_with_home_browse_and_public_active_products(self):
        visible_products = [self._add_product(f"visible-{number}") for number in range(5)]
        sold_product = self._add_product("sold-product", STATUS_SOLD)
        hidden_by_listing_limit = self._add_product("hidden-product")
        db.session.commit()

        response = self.client.get("/sitemap.xml", headers={"Host": "market.example.test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/xml")
        root = ElementTree.fromstring(response.data)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        url_elements = root.findall("sm:url", namespace)
        locations = [element.findtext("sm:loc", namespaces=namespace) for element in url_elements]
        self.assertIn("http://market.example.test/", locations)
        self.assertIn("http://market.example.test/browse", locations)
        self.assertEqual(
            len(locations),
            2 + len(visible_products),
        )
        self.assertNotIn(
            f"http://market.example.test/p/{sold_product.slug}",
            locations,
        )
        self.assertNotIn(
            f"http://market.example.test/p/{hidden_by_listing_limit.slug}",
            locations,
        )
        for product in visible_products:
            self.assertIn(f"http://market.example.test/p/{product.slug}", locations)
            product_url = next(
                element for element in url_elements
                if element.findtext("sm:loc", namespaces=namespace)
                == f"http://market.example.test/p/{product.slug}"
            )
            self.assertEqual(
                product_url.findtext("sm:lastmod", namespaces=namespace),
                product.created_at.date().isoformat(),
            )
            self.assertEqual(
                product_url.findtext("sm:changefreq", namespaces=namespace),
                "weekly",
            )
            self.assertEqual(
                product_url.findtext("sm:priority", namespaces=namespace),
                "0.8",
            )

        static_page = next(
            element for element in url_elements
            if element.findtext("sm:loc", namespaces=namespace) == "http://market.example.test/"
        )
        self.assertEqual(
            static_page.findtext("sm:lastmod", namespaces=namespace),
            datetime.now(timezone.utc).date().isoformat(),
        )
        self.assertEqual(
            static_page.findtext("sm:changefreq", namespaces=namespace),
            "daily",
        )
        self.assertEqual(
            static_page.findtext("sm:priority", namespaces=namespace),
            "1.0",
        )

    def test_google_site_verification_endpoint_returns_verification_file(self):
        response = self.client.get("/google1fc7af632ee3cc17.html")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_data(as_text=True).strip(),
            "google-site-verification: google1fc7af632ee3cc17.html",
        )
        response.close()


if __name__ == "__main__":
    unittest.main()
