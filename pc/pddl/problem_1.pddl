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

    ;; --- Sensor states ---
    (motion-detected zone1)
    (light-normal zone1)
    (temperature-high zone1)
    (humidity-low zone1)

    ;; --- Ultrasonic confirms product is physically present ---
    (product-available item1 zone1)

    ;; --- UI button: Deliver to Frankfurt = guide LEFT ---
    (delivery-requested-left item1 zone1)

  )

  (:goal
    (and
      (led-on zone1)
      (fan-on zone1)
      (humidifier-on zone1)
      (delivered-left item1)
    )
  )
)
