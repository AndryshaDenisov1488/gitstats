---
name: ffkm-server
description: >-
  Общий доступ по SSH к production VPS ФФКМ (46.173.17.188:2222).
  Секреты FFKM_SSH_* одинаковы для ВСЕХ репозиториев/агентов.
  Для сервиса на сервере: push origin main → деплой в /opt/<project> → restart.
  consents: scripts/deploy-production.sh → /opt/ffkm-consent, systemd ffkm-consent.
---

# FFKM Server — общий SSH для всех агентов

Этот skill **не привязан только к consent**. Его можно (и нужно) копировать в любой репозиторий ФФКМ, которому нужен прод-сервер.

## Секреты один раз на всё

В Cursor: **Cloud Agents → Environments → New / Start Setup**

1. Создай **одно** Environment (например `ffkm-prod`).
2. В **Repositories** добавь **все** нужные репо (не только `ffkm-consent`).
3. В **Secrets** этого environment:

| Имя | Тип | Значение |
|-----|-----|----------|
| `FFKM_SSH_HOST` | Env var | `46.173.17.188` |
| `FFKM_SSH_PORT` | Env var | `2222` |
| `FFKM_SSH_USER` | Env var | `root` |
| `FFKM_SSH_PRIVATE_KEY` | **Runtime Secret** | весь текст приватного ключа |

Публичный ключ уже должен быть в `/root/.ssh/authorized_keys` на сервере.

После этого **любой** Cloud Agent, стартующий из репо этого Environment, видит те же `FFKM_SSH_*` и может зайти на сервер.

Routing Rules (опционально): направь нужные репо на environment `ffkm-prod`.

## Как зайти по SSH (из любого агента / репо)

```bash
# 1) Материализовать ключ из secret (если ещё нет файла)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
printf '%s\n' "${FFKM_SSH_PRIVATE_KEY}" | sed 's/\\n/\n/g' > ~/.ssh/ffkm_ed25519
chmod 600 ~/.ssh/ffkm_ed25519

# 2) Подключение
ssh -i ~/.ssh/ffkm_ed25519 -p "${FFKM_SSH_PORT:-2222}" \
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new \
  "${FFKM_SSH_USER:-root}@${FFKM_SSH_HOST:-46.173.17.188}"
```

Если в репозитории есть хелпер:

```bash
bash scripts/ssh-ffkm.sh
bash scripts/ssh-ffkm.sh 'hostname; ls /opt'
```

## Карточка сервера

| | |
|--|--|
| Host | `46.173.17.188` |
| SSH | порт **2222**, user **root** |
| Каталог проектов | `/opt/` |

### Известные сервисы на этом VPS

| Сервис | Path | Systemd | URL | Деплой |
|--------|------|---------|-----|--------|
| Согласия ПДн | `/opt/ffkm-consent` | `ffkm-consent` | https://consent.ffkm.ru | в репо consent: `bash scripts/deploy-production.sh` |

Другие проекты: тот же SSH; путь/юнит/команда деплоя — в skill **этого** репозитория.

## Обязательный цикл после изменений кода (типовой)

1. `git commit`
2. `git push origin main`
3. На сервере: `git fetch && git reset --hard origin/main` в каталоге проекта, deps, `systemctl restart <unit>`, health-check.

Для **ffkm-consent** пункт 3 = `bash scripts/deploy-production.sh` (уже делает всё сам).

Без выката на сервер задача по прод-сервису **не завершена**.

## Как дать этот skill другим репозиториям

Скопируй папку целиком:

```text
.cursor/skills/ffkm-server/SKILL.md
```

плюс по желанию `scripts/ssh-ffkm.sh` из `ffkm-consent`.  
Деплой-скрипт каждого сервиса остаётся своим (`deploy-production.sh` только для consent).

## Запрещено

- Класть приватный ключ / пароли в git или в текст skill.
- Путать **Self-Hosted workers** (запуск агента у себя) с SSH на этот VPS.

## Связанные skills

- Согласия: `.cursor/skills/ffkm-consent/SKILL.md` (только репо consent)
