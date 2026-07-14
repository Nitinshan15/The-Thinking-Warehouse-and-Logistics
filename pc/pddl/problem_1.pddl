;; ============================================================
;; Problem instance — zone1 / building1
;; "Deliver left" button pressed, ultrasonic confirms product present.
;; ============================================================

(define (problem zone1-building1-deliver-left)
  (:domain smart-zone-control)

  (:objects
    building1 - building
    zone1     - zone
    item1     - item
  )

  (:init
    (zone-in-building zone1 building1)

    (light-high zone1)
    (temperature-high zone1)
    (humidity-high zone1)

  )

  (:goal
    (and
      (led-on zone1)
      (fan-on zone1)
      (humidifier-on zone1)
    )
  )
)
