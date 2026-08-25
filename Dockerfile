FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    AI_QUOTE_API_HOST=0.0.0.0 \
    PSQL_PATH=/usr/bin/psql \
    PGSSLMODE=require

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY api/server.mjs api/attachment_rules.mjs api/attachment_catalog_rules.mjs api/attachment_catalog_query.mjs api/door_variant_rules.mjs api/history_price_query.mjs api/runtime_config.mjs ./api/
COPY exceljs_range_adapter.mjs quote_export_contract.mjs export_dual_quote_workbook.mjs ./

RUN chown -R node:node /app
USER node

EXPOSE 10000
CMD ["node", "api/server.mjs"]
