## Promoción a producción

- [ ] El PR usa `bundle_work` como origen y `main` como destino.
- [ ] `app_version` aumentó según el alcance del cambio.
- [ ] El deploy de staging correspondiente a este SHA está `Live`.
- [ ] Se validó en staging el comportamiento afectado en escritorio y móvil.
- [ ] No se incluyeron secretos, credenciales ni datos productivos.
- [ ] Los checks `Version check` y `Promotion gate` finalizaron correctamente.
- [ ] El responsable del sitio aprobó promover esta versión.

Después del merge, producción se despliega manualmente desde Render verificando
que el SHA de `main` coincida con el aprobado en este PR.
