# Datasource Definitions

Datasource YAML files describe how Praeparo visuals obtain data. Place them under a project's `datasources/` folder and set the `type` discriminator so the resolver knows which provider to use.

## Power BI datasources

`type: powerbi` connects to the Power BI REST API. Fields accept literal values or `${env:VAR}` placeholders.

```yaml
# projects/quarterly-review/datasources/default.yaml
type: powerbi
datasetId: "${env:PRAEPARO_PBI_DATASET_ID}"
workspaceId: "${env:PRAEPARO_PBI_WORKSPACE_ID}"
# Optional overrides when you do not want to rely on global env vars
# tenantId: "${env:PRAEPARO_PBI_TENANT_ID}"
# clientId: "${env:PRAEPARO_PBI_CLIENT_ID}"
# clientSecret: "${env:PRAEPARO_PBI_CLIENT_SECRET}"
# refreshToken: "${env:PRAEPARO_PBI_REFRESH_TOKEN}"
# scope: "https://analysis.windows.net/powerbi/api/.default"
```

When fields are omitted the resolver falls back to environment variables:

- `PRAEPARO_PBI_DATASET_ID`
- `PRAEPARO_PBI_WORKSPACE_ID`
- `PRAEPARO_PBI_TENANT_ID`
- `PRAEPARO_PBI_CLIENT_ID`
- `PRAEPARO_PBI_CLIENT_SECRET`
- `PRAEPARO_PBI_REFRESH_TOKEN`
- `PRAEPARO_PBI_SCOPE` (optional)

If a required value cannot be resolved, the CLI raises a configuration error before issuing a query.

## Mock datasource behaviour

When no datasource is specified (or `datasource` is left blank in a visual), the CLI uses the deterministic mock provider. This is ideal for rapid prototyping and snapshot-based tests, so you do not need to create a separate `mock` YAML file.

## Future providers

Additional datasource types (SQL, CSV, HTTP, etc.) will follow the same pattern: a `type` discriminator and a resolver defined in `praeparo.datasources`. Keep project documentation updated as new providers are introduced.
