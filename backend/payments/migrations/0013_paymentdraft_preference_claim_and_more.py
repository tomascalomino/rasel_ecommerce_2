from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0012_paymentdraft_coupon_paymentdraft_coupon_code_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentdraft',
            name='preference_claim',
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='paymentdraft',
            name='preference_claim_until',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
