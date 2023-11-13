# Ubo Application

## Contribution

```sh
poetry install # You need `--with development` if you want to run it on a non-raspberry machine
poetry run app
```

## Conventions

1. Use `UBO_` prefix for all environment variables, additional prefixed may come after `UBO_` as needed.
1. Never modify state out of reducers (it will be overridden)
