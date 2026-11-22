"""One receipt per actor and idempotency key. Never discard old receipts."""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint('uq_command_actor_msg', 'command_log', ['actor_user_id', 'msg_id'])
    op.add_column('command_log', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('command_log', sa.Column('error_code', sa.Integer(), nullable=True))


def downgrade():
    # InnoDB may discard the implicit FK index when the composite key replaces it.
    indexes = sa.inspect(op.get_bind()).get_indexes('command_log')
    if not any(i['name'] == 'fk_command_log_actor_user' for i in indexes):
        op.create_index('fk_command_log_actor_user', 'command_log', ['actor_user_id'])
    op.drop_column('command_log', 'error_code')
    op.drop_column('command_log', 'updated_at')
    op.drop_constraint('uq_command_actor_msg', 'command_log', type_='unique')
