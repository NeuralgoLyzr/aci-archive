"""
Run database migrations at startup if RUN_MIGRATIONS environment variable is set to 'true'.
This ensures the database schema is up-to-date before the server starts.
"""

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from aci.common.logging_setup import get_logger

logger = get_logger(__name__)


def run_migrations() -> None:
    """Run Alembic migrations to upgrade database to latest version."""
    
    # Check if migrations should run
    should_run = os.getenv("RUN_MIGRATIONS", "false").lower() == "true"
    
    if not should_run:
        logger.info("Skipping database migrations (RUN_MIGRATIONS not set to 'true')")
        return
    
    logger.info("🔄 Running database migrations...")
    
    try:
        # Get the backend directory (where alembic.ini is located)
        backend_dir = Path(__file__).parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        
        if not alembic_ini.exists():
            logger.error(f"❌ alembic.ini not found at {alembic_ini}")
            raise FileNotFoundError(f"alembic.ini not found at {alembic_ini}")
        
        logger.info(f"Using alembic.ini at: {alembic_ini}")
        
        # Create Alembic config object
        alembic_cfg = Config(str(alembic_ini))
        
        # Set the script location to the correct path
        script_location = str(backend_dir / "aci" / "alembic")
        alembic_cfg.set_main_option("script_location", script_location)
        logger.info(f"Script location: {script_location}")
        
        # Configure Alembic to use our logger
        import logging
        logging.getLogger('alembic').setLevel(logging.INFO)
        
        # Check current database revision
        try:
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            from aci.common.utils import create_db_session
            from aci.server import config as server_config
            
            script = ScriptDirectory.from_config(alembic_cfg)
            head_revision = script.get_current_head()
            logger.info(f"Latest migration revision: {head_revision}")
            
            # Check current DB revision
            with create_db_session(server_config.get_db_full_url_sync()) as db:
                context = MigrationContext.configure(db.connection())
                current_rev = context.get_current_revision()
                
                if current_rev:
                    logger.info(f"Current database revision: {current_rev}")
                    if current_rev == head_revision:
                        logger.info("✅ Database is already up-to-date, no migrations needed")
                        return
                else:
                    logger.info("Database has no revision (fresh database or pre-alembic)")
        except Exception as check_error:
            logger.warning(f"Could not check database revision: {check_error}")
            logger.info("Proceeding with migration anyway...")
        
        # Run the upgrade command with timeout handling
        logger.info("Running alembic upgrade head...")
        logger.info("This may take a few moments if there are many migrations...")
        logger.info("Found migration script location: " + str(backend_dir / "aci" / "alembic"))
        
        # Add timeout using signal (only on Unix systems)
        import signal
        import sys
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Migration timed out after 5 minutes")
        
        # Only set timeout on Unix systems (not Windows)
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(300)  # 5 minute timeout
        
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("✅ Database migrations completed successfully")
        except TimeoutError as te:
            logger.error(f"❌ Migration timed out: {te}")
            logger.error("This usually means:")
            logger.error("  1. Another process is holding a database lock")
            logger.error("  2. A migration is taking too long")
            logger.error("  3. Database connection is slow/unstable")
            raise
        except Exception as migration_error:
            logger.error(f"❌ Migration failed during execution: {migration_error}")
            logger.error(f"Error type: {type(migration_error).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        finally:
            # Cancel alarm if set
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
            
    except FileNotFoundError as e:
        logger.error(f"❌ Migration failed: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error during migration: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise


def check_migration_status() -> None:
    """Check current migration status without running migrations."""
    try:
        backend_dir = Path(__file__).parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        
        if not alembic_ini.exists():
            logger.warning(f"⚠️  alembic.ini not found at {alembic_ini}")
            return
        
        # Create Alembic config object
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(backend_dir / "aci" / "alembic"))
        
        # Get current revision
        from alembic.script import ScriptDirectory
        from aci.common.db import get_db_session
        from aci.server import config as server_config
        
        script = ScriptDirectory.from_config(alembic_cfg)
        
        with get_db_session(server_config.get_db_full_url_sync()) as db:
            from alembic.migration import MigrationContext
            context = MigrationContext.configure(db.connection())
            current_rev = context.get_current_revision()
            
            if current_rev:
                logger.info(f"📊 Current database revision: {current_rev}")
            else:
                logger.warning("⚠️  No database revision found (database might be empty)")
            
    except Exception as e:
        logger.warning(f"⚠️  Could not check migration status: {e}")


if __name__ == "__main__":
    # Allow running this script directly for testing
    run_migrations()
