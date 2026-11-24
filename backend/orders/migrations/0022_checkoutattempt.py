import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0021_order_coupon_order_coupon_code_and_more'),
        ('payments', '0013_paymentdraft_preference_claim_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CheckoutAttempt',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('session_digest', models.CharField(db_index=True, max_length=64)),
                ('draft', models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='checkout_attempt', to='payments.paymentdraft')),
                ('order', models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='checkout_attempt', to='orders.order')),
            ],
            options={
                'constraints': [models.CheckConstraint(condition=models.Q(models.Q(('draft__isnull', True), ('order__isnull', False)), models.Q(('draft__isnull', False), ('order__isnull', True)), _connector='OR'), name='checkout_attempt_one_result')],
            },
        ),
    ]
