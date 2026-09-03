from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OrderFulfillmentMigrationTests(TransactionTestCase):
    migrate_from = ("orders", "0015_order_payment_discount_percent")
    migrate_to = ("orders", "0016_separate_payment_and_fulfillment")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        OldOrder = old_apps.get_model("orders", "Order")

        base = {
            "full_name": "Histórico",
            "email": "historico@example.com",
            "total_amount": Decimal("100.00"),
            "payment_method": "transfer",
        }
        self.ids = {
            "pending": OldOrder.objects.create(
                **base, status="pending", payment_status="pending"
            ).pk,
            "paid": OldOrder.objects.create(
                **base, status="paid", payment_status="approved"
            ).pk,
            "review": OldOrder.objects.create(
                **base, status="payment_review", payment_status="review"
            ).pk,
            "shipped": OldOrder.objects.create(
                **base,
                status="shipped",
                payment_status="approved",
                delivery_method="ship",
            ).pk,
            "pickup": OldOrder.objects.create(
                **base,
                status="shipped",
                payment_status="approved",
                delivery_method="pickup",
            ).pk,
            "cancelled": OldOrder.objects.create(
                **base, status="cancelled", payment_status="cancelled"
            ).pk,
        }

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_historical_states_are_split_without_assuming_delivery(self):
        Order = self.apps.get_model("orders", "Order")
        expected = {
            "pending": "pending",
            "paid": "pending",
            "review": "pending",
            "shipped": "shipped",
            "pickup": "ready_for_pickup",
            "cancelled": "cancelled",
        }
        for key, fulfillment_status in expected.items():
            order = Order.objects.get(pk=self.ids[key])
            self.assertEqual(order.fulfillment_status, fulfillment_status)
            self.assertIsNone(order.completed_at)
            self.assertFalse(order.completion_email_sent)
