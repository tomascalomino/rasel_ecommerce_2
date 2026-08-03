# Historial de funcionamiento

Este historial registra cambios ya aplicados. El comportamiento vigente se
documenta en `CURRENT_SYSTEM.md` y los procedimientos en `OPERATIONS.md`.

## 2026-08-02 — Checkout Pro seguro y conciliable

- Cambio aplicado: se reemplazó el flujo legado de Mercado Pago por Checkout
  Pro con SDK oficial, preferencias idempotentes, reservas de stock, retorno
  verificado por API, webhook firmado antes de toda escritura, estados
  financieros, reintegros sincronizados y revisión manual de anomalías.
- Flujo afectado: checkout, stock, pagos, retornos, webhooks, emails, admin,
  conciliación e incidentes. Transferencia y efectivo conservan su flujo.
- Migraciones o variables: `orders.0013` y `payments.0007`; se sustituye
  `MP_ENABLED` por `MP_CHECKOUT_ENABLED`, ambiente, límites de cuotas/reserva,
  plazo pendiente y email de alertas. Se agrega `mercadopago==3.3.0`.
- Operación: se agrega `reconcile_mp_payments` y el Blueprint declara
  `rasel-mp-reconcile` cada diez minutos. Checkout continúa apagado por defecto
  hasta completar staging, credenciales, webhook, cron y prueba controlada.
- Documentación actualizada: `README.md`, `docs/CURRENT_SYSTEM.md`,
  `docs/OPERATIONS.md` y `docs/CHANGELOG.md`.

## Formato para nuevas entradas

```md
## AAAA-MM-DD — Título breve

- Cambio aplicado: ...
- Flujo afectado: ...
- Migraciones o variables: ...
- Documentación actualizada: ...
```

## 2026-08-02 — Baseline documental auditado

- Cambio aplicado: se reemplazó la documentación histórica fragmentada por una
  descripción del sistema actual, un manual de operación y este historial.
- Flujo afectado: despliegue, catálogo, checkout, pedidos, emails,
  administración, recuperación y servicios externos.
- Migraciones o variables: no se modificaron migraciones ni valores de
  producción; se documentaron las variables existentes.
- Documentación actualizada: `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `docs/CURRENT_SYSTEM.md` y `docs/OPERATIONS.md`.
- Base auditada: `bundle_work` en `384e455`; producción en `rasel.ar`.
