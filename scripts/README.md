# Scripts de operación

## Backups (DB + uploads)

`backup.sh` hace una copia consistente de la base SQLite (vía `sqlite3 .backup`,
seguro aun con la app corriendo) y un `tar.gz` de los archivos subidos, con
rotación automática.

### Setup en el servidor (una sola vez)

```bash
# 1. Asegurar que sqlite3 esté instalado
apt install -y sqlite3

# 2. Permisos de ejecución
chmod +x /var/www/ratoneando-austral/scripts/backup.sh
chmod +x /var/www/ratoneando-austral/scripts/restore.sh

# 3. Probar una corrida manual
bash /var/www/ratoneando-austral/scripts/backup.sh

# 4. Programar cron diario a las 03:00
crontab -e
# agregar la línea:
0 3 * * * /var/www/ratoneando-austral/scripts/backup.sh >> /var/log/ratoneando-backup.log 2>&1
```

Los backups quedan en `/var/backups/ratoneando/<timestamp>/` y se retienen 14 días
(configurable con `RETENTION_DAYS`).

> **Importante:** estos backups viven en el mismo servidor. Para protegerte de una
> pérdida total del disco/VPS, copialos también afuera (otro host, S3, rsync a otra
> máquina). Un backup en el mismo disco que la DB no te salva de un fallo de disco.

### Restaurar

```bash
bash /var/www/ratoneando-austral/scripts/restore.sh /var/backups/ratoneando/20260604-030000
```

Pide confirmación porque sobreescribe los datos actuales. Reiniciá la app después.
