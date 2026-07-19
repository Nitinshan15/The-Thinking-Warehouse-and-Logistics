;; Auto-generated from live warehouse telemetry
(define (problem problem_81)
  (:domain smart-zone-control)

  (:objects
    building1 - building
    zone1 - zone
    item_INV-001_1 - item
  )

  (:init
    (zone-in-building zone1 building1)


  ;;SENSORS state
    (light-low zone1)
    (indoor-temp-ideal zone1)
    (humidity-low zone1)
    (outdoor-temp-cold)

  ;;ACTUATORS state
    (fan-off zone1)
    (window-closed zone1)
    (heater-off zone1)
    (led-on zone1)
    (humidifier-on zone1)
  )

  (:goal
    (and
      (control-lights zone1)
      (comfortable zone1)
      (control-humidity zone1)
    )
  )
)
