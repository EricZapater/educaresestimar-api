"""add_clients_billing_and_recurring_series

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-29 08:50:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Taula clients
    op.create_table(
        "clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("reset_token_hash", sa.Text(), nullable=True),
        sa.Column("reset_token_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_clients_email"),
    )

    # 2. Taula client_session_prices
    op.create_table(
        "client_session_prices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("session_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("client_id", "session_type_id", name="uq_client_session_price"),
    )

    # 3. Preu base a session_types
    op.add_column(
        "session_types",
        sa.Column("default_price", sa.Numeric(10, 2), server_default=sa.text("0"), nullable=False),
    )

    # 4. Camps de client, sèrie periòdica i cobraments a reservations
    op.add_column(
        "reservations",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_reservations_client_id",
        "reservations",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "reservations",
        sa.Column("recurrence_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_reservations_recurrence_group_id",
        "reservations",
        ["recurrence_group_id"],
    )
    op.add_column(
        "reservations",
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("amount_paid", sa.Numeric(10, 2), server_default=sa.text("0"), nullable=False),
    )

    # 5. Backfill d'històric: agrupar reserves existents en fitxes de clients
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, client_name, client_phone, client_email "
            "FROM reservations ORDER BY created_at ASC"
        )
    ).fetchall()

    by_email: dict[str, str] = {}
    by_phone: dict[str, str] = {}
    client_emails: dict[str, str | None] = {}

    for row in rows:
        res_id = str(row[0])
        raw_name = (row[1] or "Client").strip() or "Client"
        raw_phone = (row[2] or "").strip()
        raw_email = (row[3] or "").strip().lower()
        email_norm = raw_email if raw_email else None
        phone_digits = "".join(ch for ch in raw_phone if ch.isdigit())

        cid: str | None = None
        if email_norm and email_norm in by_email:
            cid = by_email[email_norm]
        elif phone_digits and phone_digits in by_phone:
            cid = by_phone[phone_digits]
            if email_norm and client_emails.get(cid) is None and email_norm not in by_email:
                bind.execute(
                    sa.text("UPDATE clients SET email = :email WHERE id = CAST(:id AS uuid)"),
                    {"email": email_norm, "id": cid},
                )
                client_emails[cid] = email_norm
                by_email[email_norm] = cid

        if cid is None:
            cid = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO clients (id, name, phone, email) "
                    "VALUES (CAST(:id AS uuid), :name, :phone, :email)"
                ),
                {
                    "id": cid,
                    "name": raw_name,
                    "phone": raw_phone,
                    "email": email_norm,
                },
            )
            client_emails[cid] = email_norm
            if email_norm:
                by_email[email_norm] = cid
            if phone_digits:
                by_phone[phone_digits] = cid

        bind.execute(
            sa.text(
                "UPDATE reservations SET client_id = CAST(:cid AS uuid), price = COALESCE(price, 0) "
                "WHERE id = CAST(:rid AS uuid)"
            ),
            {"cid": cid, "rid": res_id},
        )


def downgrade() -> None:
    op.drop_column("reservations", "amount_paid")
    op.drop_column("reservations", "price")
    op.drop_index("ix_reservations_recurrence_group_id", table_name="reservations")
    op.drop_column("reservations", "recurrence_group_id")
    op.drop_constraint("fk_reservations_client_id", "reservations", type_="foreignkey")
    op.drop_column("reservations", "client_id")
    op.drop_column("session_types", "default_price")
    op.drop_table("client_session_prices")
    op.drop_table("clients")
