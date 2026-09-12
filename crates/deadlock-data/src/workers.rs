use crate::error::{Error, Result};
use std::sync::atomic::{AtomicUsize, Ordering};

/// # Errors
/// Returns an error for zero workers, a failed operation, or an unexpected worker stop.
pub fn map_jobs<T: Sync, R: Send>(
    jobs: &[T],
    workers: u16,
    operation: impl Fn(&T) -> Result<R> + Sync,
) -> Result<Vec<R>> {
    map_jobs_by_cost(jobs, workers, |_| 0, operation)
}

/// # Errors
/// Returns an error for zero workers, a failed operation, or an unexpected worker stop.
pub fn map_jobs_by_cost<T: Sync, R: Send>(
    jobs: &[T],
    workers: u16,
    cost: impl Fn(&T) -> u64,
    operation: impl Fn(&T) -> Result<R> + Sync,
) -> Result<Vec<R>> {
    if workers == 0 {
        return Err(Error::new("Job execution requires at least one worker"));
    }
    if jobs.is_empty() {
        return Ok(Vec::new());
    }
    let mut order = (0..jobs.len()).collect::<Vec<_>>();
    order.sort_by_cached_key(|index| std::cmp::Reverse(cost(&jobs[*index])));
    let next = AtomicUsize::new(0);
    std::thread::scope(|scope| {
        let handles = (0..usize::from(workers).min(jobs.len()))
            .map(|_| {
                let operation = &operation;
                let next = &next;
                let order = &order;
                scope.spawn(move || {
                    let mut results = Vec::new();
                    while let Some((index, job)) = claim_job(jobs, order, next) {
                        results.push((index, operation(job)));
                    }
                    results
                })
            })
            .collect::<Vec<_>>();
        let mut output = Vec::with_capacity(jobs.len());
        let mut failure = None;
        for handle in handles {
            match handle
                .join()
                .map_err(|_| Error::new("Job worker stopped unexpectedly"))
            {
                Ok(results) => output.extend(results),
                Err(error) => {
                    if failure.is_none() {
                        failure = Some(error);
                    }
                }
            }
        }
        if let Some(error) = failure {
            return Err(error);
        }
        output.sort_by_key(|(index, _)| *index);
        output.into_iter().map(|(_, result)| result).collect()
    })
}

fn claim_job<'a, T>(jobs: &'a [T], order: &[usize], next: &AtomicUsize) -> Option<(usize, &'a T)> {
    let index = *order.get(next.fetch_add(1, Ordering::Relaxed))?;
    jobs.get(index).map(|job| (index, job))
}
