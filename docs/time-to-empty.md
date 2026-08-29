# Time-to-empty algorithms

The two time-to-empty commands use the same input format but construct
different probability models:

1. `tsd-mc-time-to-empty` samples daily consumption rates from the observed
   history.
2. `tsd-time-to-empty` estimates a latent consumption rate with a Kalman
   filter and simulates that rate as a Gaussian random walk.

In both commands, quantity is denoted by $q$, consumption rate by $r$, and
time in days by $t$. A positive consumption rate reduces the quantity.

## Common input processing

An input observation is a pair

$$
(d_i, q_i),
$$

where $d_i$ is a calendar date and $q_i$ is the observed quantity.

Both commands:

- ignore blank lines, comments, and malformed observations;
- round parsed quantities to integer-valued floats;
- sort observations by date; and
- by default, retain only the last input observation for each date.

With `--keep-same-day`, observations on the same date are retained. Intervals
with zero elapsed time do not contribute a daily rate.

If the last observed quantity is non-positive, both commands report the
series as already empty and do not run a forward simulation.

## `tsd-mc-time-to-empty`

### Historical daily rates

For each pair of consecutive observations, define

$$
\Delta t_i = d_i - d_{i-1}
$$

and

$$
\Delta q_i = q_{i-1} - q_i.
$$

Only intervals with $\Delta t_i > 0$ are considered.

If $\Delta q_i < 0$, the quantity increased. The entire interval is
classified as a refill interval and excluded from the historical sampling
population.

Otherwise, the interval contributes the daily rate

$$
r_i = \frac{\Delta q_i}{\Delta t_i}.
$$

The rate $r_i$ is inserted into the historical population once for every
day in the interval. An interval of length $\Delta t_i$ therefore contributes
$\Delta t_i$ copies of $r_i$. This makes the unweighted probability of
selecting an interval rate proportional to the interval's duration.

A flat interval has $\Delta q_i = 0$, so it contributes zero-valued daily
rates.

### Recency weighting

Each historical daily rate is associated with its calendar day. Let $a_j$
be the age of historical day $j$, measured backward from the date of the
latest observation. Its unnormalized sampling weight is

$$
\widetilde{w}_j =
1 + A \exp\left(-\frac{1}{2}
                    \left(\frac{a_j}{\sigma}\right)^2\right),
$$

where:

- $\sigma$ is `--recency-sigma`, in days; and
- $A$ is `--recency-amplitude`.

The defaults are $\sigma=60$ days and $A=1$. The constant term gives every
historical day a baseline weight of 1. The Gaussian term adds $A$ at age
zero and approaches zero as age increases.

The weights used for sampling are normalized:

$$
w_j = \frac{\widetilde{w}_j}
           {\sum_k \widetilde{w}_k}.
$$

When $A=0$, all included historical days have equal weight.

The reported historical mean is

$$
\overline{r} = \frac{1}{m}\sum_{j=1}^{m} r_j,
$$

where $m$ is the number of included historical days. The reported
recency-weighted mean is

$$
\overline{r}_w = \sum_{j=1}^{m} w_j r_j.
$$

### Forward simulation

Each simulation starts at the last observed quantity:

$$
Q_0 = q_{n-1}.
$$

For each future whole-day step $k$, the program independently samples an
index $J_k$ with

$$
\Pr(J_k=j)=w_j
$$

and updates the simulated quantity by

$$
Q_k = Q_{k-1} - r_{J_k}.
$$

Sampling is with replacement. Samples are independent between future days
and between simulation paths.

The hitting time is the first whole-day step at which the quantity is
non-positive:

$$
T = \min\{k : Q_k \leq 0\}.
$$

The default number of simulation paths is 20,000. A path that does not reach
zero by `--max-days` is right-censored and represented internally by
infinity.

If every historical daily rate is zero, every non-empty simulation is
censored.

If the current quantity is positive but there are no usable non-increasing
intervals, the command reports an error rather than running a simulation.

## `tsd-time-to-empty`

### Consumption-only observation series

The state-space command first replaces raw quantity changes with non-negative
consumption increments:

$$
c_i = \max(q_{i-1}-q_i, 0).
$$

An increase in the raw quantity therefore contributes $c_i=0$. Unlike the
empirical command, the corresponding time interval remains in the
state-space observation sequence as an interval with no decrease.

The program constructs an adjusted quantity series $z_i$, anchored at the
last raw observation:

$$
z_{n-1}=q_{n-1},
$$

$$
z_{i-1}=z_i+c_i.
$$

Equivalently,

$$
z_i=q_{n-1}+\sum_{j=i+1}^{n-1}c_j.
$$

The adjusted series is non-increasing and preserves every observed decrease
while removing every observed increase.

### Initial rate and covariance

For every positive adjusted decrease over a positive-length interval, the
program computes

$$
\rho_i = \frac{z_{i-1}-z_i}{t_i-t_{i-1}}.
$$

The initial rate estimate is the median of the positive $\rho_i$. If there
are no positive rates, the initial rate is $10^{-6}$.

The initial state and covariance are

$$
\widehat{x}_0 =
\begin{bmatrix}
z_0 \\
\widehat{r}_0
\end{bmatrix},
\qquad
P_0 =
\begin{bmatrix}
10^2 & 0 \\
0 & 1^2
\end{bmatrix}.
$$

The state vector contains quantity and consumption rate:

$$
x_i =
\begin{bmatrix}
q_i \\
r_i
\end{bmatrix}.
$$

### State transition model

For an observation interval, the filter uses

$$
\Delta t_i=\max(t_i-t_{i-1},10^{-9}).
$$

The transition matrix is

$$
F_i =
\begin{bmatrix}
1 & -\Delta t_i \\
0 & 1
\end{bmatrix}.
$$

The process covariance is

$$
Q_i =
\begin{bmatrix}
\sigma_q^2\Delta t_i & 0 \\
0 & \sigma_r^2\Delta t_i
\end{bmatrix},
$$

where $\sigma_q$ is `--sigma-q` and $\sigma_r$ is `--sigma-r`.
Their defaults are 0.25 and 0.50 per square root day, respectively.

Thus the state model is

$$
x_i = F_i x_{i-1} + \eta_i,
\qquad
\eta_i \sim \mathcal{N}(0,Q_i).
$$

The rate component is a random walk. The quantity component decreases by the
rate multiplied by elapsed time and has independent process noise.

### Observation model and Kalman update

Only quantity is observed:

$$
z_i = Hx_i+\epsilon_i,
\qquad
H =
\begin{bmatrix}
1 & 0
\end{bmatrix},
\qquad
\epsilon_i\sim\mathcal{N}(0,\sigma_z^2),
$$

where $\sigma_z$ is `--sigma-z`.
Its default is 0.50.

For each observation after the first, the prediction step is

$$
\widehat{x}_i^- = F_i\widehat{x}_{i-1},
$$

$$
P_i^- = F_iP_{i-1}F_i^\mathsf{T}+Q_i.
$$

The innovation, innovation variance, and Kalman gain are

$$
y_i=z_i-H\widehat{x}_i^-,
$$

$$
S_i=HP_i^-H^\mathsf{T}+\sigma_z^2,
$$

$$
K_i=P_i^-H^\mathsf{T}S_i^{-1}.
$$

The state update is

$$
\widehat{x}_i=\widehat{x}_i^-+K_i y_i.
$$

The covariance is updated in Joseph form:

$$
P_i=(I-K_iH)P_i^-(I-K_iH)^\mathsf{T}
    +K_i\sigma_z^2K_i^\mathsf{T}.
$$

After the last update, the estimated rate is bounded below by zero. The
quantity component of the state mean is then replaced by the last raw
observed quantity $q_{n-1}$. The covariance remains the covariance produced
by the Kalman filter.

With only one observation, the program uses the observed quantity, the
fallback initial rate, and the initial covariance without running update
steps.

### Forward simulation

For each simulation path, the initial state is sampled from the filtered
Gaussian:

$$
x_0^{(s)}\sim
\mathcal{N}\left(
\begin{bmatrix}
q_{n-1}\\
\widehat{r}_{n-1}
\end{bmatrix},
P_{n-1}
\right).
$$

Let $\delta$ be `--dt-forward`. At each forward step, independent Gaussian
increments are drawn:

$$
\xi_{r,k}\sim\mathcal{N}(0,\sigma_r^2\delta),
$$

$$
\xi_{q,k}\sim\mathcal{N}(0,\sigma_q^2\delta).
$$

The rate is updated first:

$$
R_k=R_{k-1}+\xi_{r,k}.
$$

Unless `--allow-negative-rate` is set, the rate is then bounded by
`--min-rate`:

$$
R_k \leftarrow \max(R_k,r_{\min}).
$$

The same bound is applied to the initially sampled rate. With
`--allow-negative-rate`, neither bound is applied.

The defaults are $\delta=1$ day and $r_{\min}=0$.

The quantity update is

$$
Q_k=Q_{k-1}+\xi_{q,k}-R_k\delta.
$$

The reported hitting time for a path is the first discrete step at which

$$
Q_k\leq 0,
$$

namely

$$
T=k\delta.
$$

The number of forward steps is

$$
\left\lceil
\frac{\text{max-days}}{\delta}
\right\rceil.
$$

A path that does not reach zero during those steps is right-censored and
represented internally by infinity.

## Reported distributions

Both commands compute requested quantiles and histograms from finite hitting
times only. They report the number and percentage of right-censored paths
separately.

The default quantiles are 10%, 25%, 50%, 75%, and 90%. The default number of
simulation paths is 20,000, and the default forward horizon is 3,650 days.
