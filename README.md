# Ubo Application

## Contribution

```sh
poetry install # You need `--with development` if you want to run it on a non-raspberry machine
poetry run app
```

## Conventions

1. Use `UBO_` prefix for all environment variables, additional prefixes may come after `UBO_` as needed.
1. Always use frozen dataclasses for action and state classes.
1. Each `action` should have only two attributes: `type` and `payload`. Payload class of an action should also be a frozen dataclass with the same name as the action class with "Payload" prefix.
