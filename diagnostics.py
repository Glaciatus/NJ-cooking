"""Local rotating diagnostics: no environment dumps, credentials or recipe bodies."""
from datetime import datetime,timezone,timedelta
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import sys

APP_VERSION='0.7.1'
LOGGER_NAME='nj_cooking'

class MoscowFormatter(logging.Formatter):
    def formatTime(self,record,datefmt=None):
        return datetime.fromtimestamp(record.created,timezone(timedelta(hours=3))).isoformat(timespec='milliseconds')


def configure_logging(directory):
    logger=logging.getLogger(LOGGER_NAME)
    close_logging(logger)
    logger.setLevel(logging.INFO)
    logger.propagate=False
    path=Path(directory)/'nj-cooking.log'
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(path,maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    except OSError:
        logger.addHandler(logging.NullHandler())
        return logger,None
    logger.handlers.clear()
    handler.setFormatter(MoscowFormatter('%(asctime)s %(levelname)s %(threadName)s %(name)s %(message)s'))
    logger.addHandler(handler)
    logger.info('startup version=%s python=%s platform=%s frozen=%s',APP_VERSION,platform.python_version(),platform.system(),bool(getattr(sys,'frozen',False)))
    return logger,path


def close_logging(logger):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.flush();handler.close()


def log_plan(logger,request_id,context,recipes):
    # Deliberate allowlist. Never serialise recipe bodies, process environment or URLs.
    fields=('seed','people','portions','kcal','protein','fat','carbs','tolerance','macro_tolerance','require_nutrition',
            'desired_tags','excluded','wanted','database_limits','enabled_databases','required_ids')
    logger.info('request=%s plan_settings=%s input_recipes=%s',request_id,{k:context[k] for k in fields if k in context},len(recipes))
    from core import recipe_key
    from nutrition import recipe_nutrition
    from estimation import servings_info
    required=set(context.get('required_ids',[]))
    for recipe in recipes:
        if recipe_key(recipe) in required:
            logger.info('request=%s required_recipe=%r key=%s servings=%s meal=%s nutrition=%s',request_id,recipe.name,recipe_key(recipe),servings_info(recipe).servings,recipe.meal,recipe_nutrition(recipe)[0])
