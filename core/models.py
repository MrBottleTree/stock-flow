from django.db import models

# Create your models here.
class Buyer(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)

    def __str__(self):
        return self.name

class Address(models.Model):
    buyer = models.ForeignKey(Buyer,
        on_delete=models.CASCADE,
        related_name="addresses"
    )
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.line1}, {self.city}"
    


class Seller(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Product(models.Model):
    seller = models.ForeignKey(
        Seller,
        on_delete=models.CASCADE,
        related_name="products"
    )
    name = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sku = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Inventory(models.Model):
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory"
    )
    quantity = models.IntegerField()
    warehouse_location = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)


class Cart(models.Model):
    buyer = models.OneToOneField(
        Buyer,
        on_delete=models.CASCADE,
        related_name="cart"
    )
    status = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CartProduct(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="cart_items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )
    quantity = models.IntegerField()

    class Meta:
        unique_together = ("cart", "product")


class Order(models.Model):
    buyer = models.ForeignKey(
        Buyer,
        on_delete=models.CASCADE,
        related_name="orders"
    )
    address = models.ForeignKey(
        Address,
        on_delete=models.PROTECT,
        related_name="orders"
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50)
    placed_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateField(blank=True, null=True)


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT
    )
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ("order", "product")
