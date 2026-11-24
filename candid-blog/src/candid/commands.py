import click
from flask import Flask

from . import services, validation
from .models import Role


def register(app: Flask) -> None:
    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("email")
    @click.option("--role", type=click.Choice([r.value for r in Role]), default="reader")
    @click.password_option()
    def create_user(username: str, email: str, role: str, password: str) -> None:
        """Create a user. The first admin must be made this way: sign-up only makes readers."""
        try:
            data = validation.registration(
                {"username": username, "email": email, "password": password}
            )
            services.register_user(data, Role(role))
        except validation.ValidationError as exc:
            raise click.ClickException(str(exc)) from None
        click.echo(f"Created {role} {username}.")
