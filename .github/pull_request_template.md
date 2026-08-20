## Promoción a producción

- [ ] El PR usa `bundle_work` como origen y `main` como destino.
- [ ] `app_version` aumentó según el alcance del cambio.
- [ ] El deploy de staging correspondiente a este SHA está `Live`.
- [ ] Se validó en staging el comportamiento afectado en escritorio y móvil.
- [ ] No se incluyeron secretos, credenciales ni datos productivos.
- [ ] La rama está actualizada con `main` y las conversaciones están resueltas.
- [ ] Los checks `app-version` y `promotion-gate` finalizaron correctamente.
- [ ] `@tomascalomino` aprobó el último SHA mediante **Review deployments** y el
      check `owner-approval` está verde.
- [ ] El método seleccionado es exclusivamente **Create a merge commit**.

La aprobación debe enviarla personalmente el propietario desde el Environment
protegido de GitHub. Ningún agente puede aprobar o rechazar el deployment,
iniciar jobs pendientes, saltar la protección ni simular la decisión mediante
API, conector, CLI o interfaz. Aprobar no activa un merge automático.

Después del merge, avanzar `bundle_work` por fast-forward a `main` y confirmar
que ambas ramas apunten al mismo SHA y árbol, sin reset ni force-push. Luego
producción se despliega manualmente desde Render, verificando que la rama sea
`main`, que Auto-Deploy continúe apagado y que el SHA coincida con el aprobado
en este PR.
