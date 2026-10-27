"""
Station-level stockout forecasting. Under development.

The read side (:mod:`lastmile.forecasting.metrics`) runs on the base install
and simply returns empty frames when nothing has been scored. Training and
scoring (:mod:`lastmile.forecasting.model`, :mod:`.features`) need the
``forecast`` extra::

    pip install -e ".[forecast]"

Nothing here is imported eagerly: the heavy modules load only when the CLI's
``lastmile forecast`` command (or a future caller) asks for them.
"""
