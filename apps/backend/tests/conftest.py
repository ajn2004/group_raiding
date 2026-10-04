def pytest_addoption(parser):
    parser.addoption("--postgres", action="store_true", help="run opt-in PostgreSQL integration tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--postgres"):
        return
    selected = [item for item in items if "postgres" in item.keywords]
    if selected:
        config.hook.pytest_deselected(items=selected)
        items[:] = [item for item in items if item not in selected]
