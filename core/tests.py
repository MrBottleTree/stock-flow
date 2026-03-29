import json

from django.test import Client, TestCase
from django.urls import reverse

from core.models import Buyer, Inventory, Product, Seller


class AuthApiTests(TestCase):
	def setUp(self):
		self.client = Client(enforce_csrf_checks=True)

	def _post_json(self, url_name, payload=None):
		return self.client.post(
			reverse(url_name),
			data=json.dumps(payload or {}),
			content_type='application/json',
		)

	def test_signup_returns_201_and_user_payload(self):
		response = self._post_json(
			'signup',
			{
				'name': 'Alice Buyer',
				'email': 'alice@example.com',
				'phone': '1234567890',
				'password': 'secret123',
				'user_type': 'buyer',
			},
		)

		self.assertEqual(response.status_code, 201)
		body = response.json()
		self.assertTrue(body['success'])
		self.assertEqual(body['user']['email'], 'alice@example.com')
		self.assertEqual(self.client.session.get('user_type'), 'buyer')

	def test_signup_duplicate_email_returns_409(self):
		self._post_json(
			'signup',
			{
				'name': 'Alice Buyer',
				'email': 'alice@example.com',
				'phone': '1234567890',
				'password': 'secret123',
				'user_type': 'buyer',
			},
		)

		second_response = self._post_json(
			'signup',
			{
				'name': 'Alice Buyer 2',
				'email': 'alice@example.com',
				'phone': '9999999999',
				'password': 'secret456',
				'user_type': 'buyer',
			},
		)

		self.assertEqual(second_response.status_code, 409)

	def test_signin_success_returns_200(self):
		self._post_json(
			'signup',
			{
				'name': 'Bob Buyer',
				'email': 'bob@example.com',
				'phone': '1234567890',
				'password': 'secret123',
				'user_type': 'buyer',
			},
		)
		self.client.post(reverse('signout'), data='{}', content_type='application/json')

		response = self._post_json(
			'signin',
			{
				'email': 'bob@example.com',
				'password': 'secret123',
				'user_type': 'buyer',
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['user']['name'], 'Bob Buyer')

	def test_signin_wrong_password_returns_401(self):
		self._post_json(
			'signup',
			{
				'name': 'Eve Buyer',
				'email': 'eve@example.com',
				'phone': '1234567890',
				'password': 'right-pass',
				'user_type': 'buyer',
			},
		)

		response = self._post_json(
			'signin',
			{
				'email': 'eve@example.com',
				'password': 'wrong-pass',
				'user_type': 'buyer',
			},
		)

		self.assertEqual(response.status_code, 401)

	def test_signout_clears_session_and_returns_200(self):
		self._post_json(
			'signup',
			{
				'name': 'Sam Seller',
				'email': 'sam@example.com',
				'phone': '1234567890',
				'password': 'secret123',
				'user_type': 'seller',
			},
		)

		response = self.client.post(reverse('signout'), data='{}', content_type='application/json')

		self.assertEqual(response.status_code, 200)
		self.assertIsNone(self.client.session.get('user_id'))

	def test_signup_post_without_csrf_token_is_allowed(self):
		response = self._post_json(
			'signup',
			{
				'name': 'No Csrf Buyer',
				'email': 'nocsrf@example.com',
				'phone': '1234567890',
				'password': 'secret123',
				'user_type': 'buyer',
			},
		)

		self.assertEqual(response.status_code, 201)
		self.assertTrue(Buyer.objects.filter(email='nocsrf@example.com').exists())


class ItemsPageAuthTests(TestCase):
	def test_items_redirects_home_when_not_logged_in(self):
		response = self.client.get(reverse('items'))
		self.assertRedirects(response, reverse('home'))

	def test_items_renders_for_valid_buyer_session(self):
		buyer = Buyer.objects.create(
			name='Buyer One',
			email='buyer1@example.com',
			phone='1234567890',
			password='x',
		)

		session = self.client.session
		session['user_id'] = buyer.id
		session['user_type'] = 'buyer'
		session['user_name'] = buyer.name
		session.save()

		response = self.client.get(reverse('items'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Items Page')

	def test_items_renders_for_valid_seller_session(self):
		seller = Seller.objects.create(
			name='Seller One',
			email='seller1@example.com',
			phone='1234567890',
			password='x',
		)

		session = self.client.session
		session['user_id'] = seller.id
		session['user_type'] = 'seller'
		session['user_name'] = seller.name
		session.save()

		response = self.client.get(reverse('items'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Items Page')

	def test_items_redirects_home_for_invalid_user_type(self):
		session = self.client.session
		session['user_id'] = 1
		session['user_type'] = 'admin'
		session['user_name'] = 'Invalid'
		session.save()

		response = self.client.get(reverse('items'))
		self.assertRedirects(response, reverse('home'))

	def test_items_redirects_home_if_session_user_missing_in_db(self):
		session = self.client.session
		session['user_id'] = 99999
		session['user_type'] = 'buyer'
		session['user_name'] = 'Ghost'
		session.save()

		response = self.client.get(reverse('items'))
		self.assertRedirects(response, reverse('home'))


class SellerInventoryPageTests(TestCase):
	def test_inventory_redirects_home_for_unauthenticated_user(self):
		response = self.client.get(reverse('inventory'))
		self.assertRedirects(response, reverse('home'))

	def test_inventory_redirects_home_for_buyer(self):
		buyer = Buyer.objects.create(
			name='Buyer Only',
			email='buyer-only@example.com',
			phone='1234567890',
			password='x',
		)

		session = self.client.session
		session['user_id'] = buyer.id
		session['user_type'] = 'buyer'
		session['user_name'] = buyer.name
		session.save()

		response = self.client.get(reverse('inventory'))
		self.assertRedirects(response, reverse('home'))

	def test_inventory_renders_for_seller(self):
		seller = Seller.objects.create(
			name='Seller Access',
			email='seller-access@example.com',
			phone='1234567890',
			password='x',
		)

		session = self.client.session
		session['user_id'] = seller.id
		session['user_type'] = 'seller'
		session['user_name'] = seller.name
		session.save()

		response = self.client.get(reverse('inventory'))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Seller Item Creation')

	def test_inventory_post_creates_product_and_inventory_for_seller(self):
		seller = Seller.objects.create(
			name='Seller Create',
			email='seller-create@example.com',
			phone='1234567890',
			password='x',
		)

		session = self.client.session
		session['user_id'] = seller.id
		session['user_type'] = 'seller'
		session['user_name'] = seller.name
		session.save()

		response = self.client.post(
			reverse('inventory'),
			data={
				'name': 'Widget Pro',
				'description': 'Premium widget for testing.',
				'image_url': 'https://example.com/widget.jpg',
				'sku': 'WIDGET-PRO-001',
				'price': '19.99',
				'quantity': '25',
				'warehouse_location': 'North Hub',
			},
		)

		self.assertRedirects(response, reverse('inventory'))
		self.assertTrue(Product.objects.filter(sku='WIDGET-PRO-001').exists())
		product = Product.objects.get(sku='WIDGET-PRO-001')
		self.assertEqual(product.seller_id, seller.id)
		self.assertTrue(Inventory.objects.filter(product=product, warehouse_location='North Hub').exists())
