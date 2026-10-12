-- Algebraic identities that must hold in every KPI row.
select account, symbol_scope, 'metric identity broken' as problem
from {{ ref('mart_kpis') }}
where n_wins + n_losses + n_scratch != n_trades
   or win_rate < 0 or win_rate > 1
   or max_drawdown_usd < 0
   or abs(net_pnl - (gross_pnl - commissions - fees)) > 1e-6
   -- expectancy = P(win) * avg_win + P(loss) * avg_loss (scratches contribute zero)
   or abs(expectancy_gross
          - (coalesce(win_rate * avg_win, 0)
             + coalesce(n_losses * 1.0 / n_trades * avg_loss, 0))) > 1e-6
