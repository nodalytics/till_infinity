"""Models trained offline and shipped as data.

The `*.json` files here are the shipped models, read by `shared/frozen.py`. `retrain.py` retrains
them on fresh bars from the terminal on a schedule, and promotes a challenger into the models
directory only when it beats the model in service on the most recent weeks neither was trained on.
"""
