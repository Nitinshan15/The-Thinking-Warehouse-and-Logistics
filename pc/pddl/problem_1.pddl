;; ============================================================
;; Problem instance — zone1 / building1
;;
;; The goal is always (delivery-request-handled item1 zone1).
;; The planner decides the path:
;;   - product-available present in :init  -> open-gate -> guide-left -> handled
;;   - product-available absent  in :init  -> notify-unavailable-left  -> handled
;;
;; To simulate "no product": remove the (product-available ...) line below.
;; ============================================================

(define (problem zone1-building1-deliver-frankfurt)
  (:domain smart-zone-control)

  (:objects
    building1 - building
    zone1     - zone
    item1     - item
  )

  (:init
    (zone-in-building zone1 building1)

    ;; --- Sensor states (raw, as received from Pi via MQTT) ---
    (motion-detected zone1)
    (light-normal zone1)
    (temperature-high zone1)
    (humidity-low zone1)

    ;; --- Ultrasonic: include this fact if sensor detects product ---
    ;; --- Omit it if no product is present — planner will notify  ---
    (product-available item1 zone1)

    ;; --- UI button: Frankfurt = Left, Stuttgart = Right ---
    (delivery-requested-left item1 zone1)
  )

  (:goal
    (and
      (led-on zone1)
      (fan-on zone1)
      (humidifier-on zone1)
      (delivery-request-handled item1 zone1)
    )
  )
)
