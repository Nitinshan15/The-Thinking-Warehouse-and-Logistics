
(define (domain smart-zone-control)

  (:requirements :strips :typing :negative-preconditions :disjunctive-preconditions )

  (:types
    building
    zone
    item
  )

  (:predicates
    (zone-in-building ?z - zone ?b - building)

    ;; --- 1) Ambience light ---
    (motion-detected ?z - zone)
    (light-low       ?z - zone)
    (light-normal    ?z - zone)
    (light-high      ?z - zone)
    (led-on          ?z - zone)
    

    (humidity-low    ?z - zone)
    (humidifier-on       ?z - zone)

    ;; Global Outdoor Sensors
    (outdoor-temp-hot)
    (outdoor-temp-cold)
    (outdoor-raining) ;; NEW VARIABLE

    ;; Zoned Indoor Sensors
    (indoor-temp-hot ?z - zone)
    (indoor-temp-cold ?z - zone)
    (indoor-temp-ideal ?z - zone)

    ;; Zoned Actuators
    (window-open ?z - zone)
    (window-closed ?z - zone)
    (fan-on ?z - zone)
    (fan-off ?z - zone)
    (heater-on ?z - zone)
    (heater-off ?z - zone)

    ;; Zoned Goal State
    (comfortable ?z - zone)
    (control-lights ?z - zone)
    (control-humidity ?z - zone)
    
    ;; --- 5) Delivery: button press = request + direction ---
    (delivery-requested-left        ?i - item ?z - zone)
    (delivery-requested-right       ?i - item ?z - zone)
    (product-available              ?i - item ?z - zone)   ; set by ultrasonic sensor
    (delivery-unavailable-notified  ?i - item ?z - zone)   ; set when no product found
    (gate-open                      ?z - zone)             ; gate motor has opened
    (delivered-left                 ?i - item)             ; which side it went, for logging
    (delivered-right                ?i - item)
    (delivery-request-handled       ?i - item ?z - zone)   ; planner sets this as terminal goal
  )

  ;; ============================================================
  ;; 1) AMBIENCE LIGHT
  ;; ============================================================

  


;; Rule: If motion + low light + we WANT lights on -> Turn them on
  (:action lights-on
    :parameters (?z - zone)
    :precondition (and (motion-detected ?z) 
                       (or (light-low ?z) (light-normal ?z)))
    :effect (and (led-on ?z) (control-lights ?z))
  )

  ;; Rule: If NO motion OR bright enough + we WANT lights off -> Ensure they are off
  (:action lights-off
    :parameters (?z - zone)
    :precondition (or (not (motion-detected ?z)) (light-high ?z))
    :effect (and (not (led-on ?z)) (control-lights ?z))
  )
  
  ;; ============================================================
  ;; 3) HUMIDITY
  ;; ============================================================


;; --- HUMIDITY RULE EVALUATORS ---

  ;; Rule: If humidity is low, we want the humidifier ON
  (:action humidifier-turn-on
    :parameters (?z - zone)
    :precondition (humidity-low ?z)
    :effect (and (humidifier-on ?z) (control-humidity ?z))
  )

  ;; Rule: If humidity is NOT low, we want the humidifier OFF
  (:action humidifier-turn-off
    :parameters (?z - zone)
    :precondition (not (humidity-low ?z))
    :effect (and (not (humidifier-on ?z)) (control-humidity ?z))
  )

;; --- ACTUATOR ACTIONS ---
  
  (:action open-window
    :parameters (?z - zone)
    ;; Prevent opening the window if it is raining
    :precondition (and (window-closed ?z) (not (outdoor-raining)))
    :effect (and (window-open ?z) (not (window-closed ?z)))
  )

  (:action close-window
    :parameters (?z - zone)
    :precondition (window-open ?z)
    :effect (and (window-closed ?z) (not (window-open ?z)))
  )

  (:action turn-fan-on
    :parameters (?z - zone)
    :precondition (fan-off ?z)
    :effect (and (fan-on ?z) (not (fan-off ?z)))
  )

  (:action turn-fan-off
    :parameters (?z - zone)
    :precondition (fan-on ?z)
    :effect (and (fan-off ?z) (not (fan-on ?z)))
  )

  (:action turn-heater-on
    :parameters (?z - zone)
    :precondition (heater-off ?z)
    :effect (and (heater-on ?z) (not (heater-off ?z)))
  )

  (:action turn-heater-off
    :parameters (?z - zone)
    :precondition (heater-on ?z)
    :effect (and (heater-off ?z) (not (heater-on ?z)))
  )

  ;; --- DECISION TREE RULE EVALUATORS ---

  ;; Rule 1 (DRY): Outdoor Hot, Indoor Cold, Not Raining -> Open Window
  (:action rule-hot-out-cold-in-dry
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-hot) (indoor-temp-cold ?z) (not (outdoor-raining)) (window-open ?z))
    :effect (comfortable ?z)
  )

  ;; Rule 1 (RAINING): Outdoor Hot, Indoor Cold, Raining -> Keep Window Closed, Heater ON
  (:action rule-hot-out-cold-in-raining
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-hot) (indoor-temp-cold ?z) (outdoor-raining) (window-closed ?z) (heater-on ?z))
    :effect (comfortable ?z)
  )
  ;; Rule 2: Outdoor Hot, Indoor Ideal -> Close Window, Fan OFF
  ;; (Naturally compatible with rain since it already requires a closed window)
  (:action rule-hot-out-ideal-in
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-hot) (indoor-temp-ideal ?z) (window-closed ?z) (fan-off ?z))
    :effect (comfortable ?z)
  )

  ;; Rule 3: Outdoor Hot, Indoor Hot -> Close Window, Fan ON
  (:action rule-hot-out-hot-in
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-hot) (indoor-temp-hot ?z) (window-closed ?z) (fan-on ?z))
    :effect (comfortable ?z)
  )

  ;; Rule 4: Outdoor Cold, Indoor Cold -> Heater ON, Close Window
  (:action rule-cold-out-cold-in
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-cold) (indoor-temp-cold ?z) (window-closed ?z) (heater-on ?z))
    :effect (comfortable ?z)
  )

  ;; Rule 5: Outdoor Cold, Indoor Ideal -> Close Window, Fan OFF
  (:action rule-cold-out-ideal-in
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-cold) (indoor-temp-ideal ?z) (window-closed ?z) (fan-off ?z))
    :effect (comfortable ?z)
  )

  ;; Rule 6 (DRY): Outdoor Cold, Indoor Hot, Not Raining -> Open Window
  (:action rule-cold-out-hot-in-dry
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-cold) (indoor-temp-hot ?z) (not (outdoor-raining)) (window-open ?z))
    :effect (comfortable ?z)
  )

;; Rule 6 (RAINING): Outdoor Cold, Indoor Hot, Raining -> Keep Window Closed, Fan ON
  (:action rule-cold-out-hot-in-raining
    :parameters (?z - zone)
    :precondition (and (outdoor-temp-cold) (indoor-temp-hot ?z) (outdoor-raining) (window-closed ?z) (fan-on ?z))
    :effect (comfortable ?z)
  )

  ;; ============================================================
  ;; 5) DELIVERY — one shared gate opens after ultrasonic check,
  ;;    then the item is guided to the requested side
  ;; ============================================================

  (:action open-gate
    :parameters (?i - item ?z - zone)
    :precondition (and (or (delivery-requested-left ?i ?z)
                           (delivery-requested-right ?i ?z))
                        (product-available ?i ?z)
                        (not (gate-open ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (gate-open ?z)
  )

  (:action guide-left
    :parameters (?i - item ?z - zone)
    :precondition (and (gate-open ?z)
                        (delivery-requested-left ?i ?z)
                        (not (delivered-left ?i))
                        (not (delivered-right ?i))
                        (not (delivery-request-handled ?i ?z)))
    :effect (and (delivered-left ?i)
                 (delivery-request-handled ?i ?z))
  )

  (:action guide-right
    :parameters (?i - item ?z - zone)
    :precondition (and (gate-open ?z)
                        (delivery-requested-right ?i ?z)
                        (not (delivered-left ?i))
                        (not (delivered-right ?i))
                        (not (delivery-request-handled ?i ?z)))
    :effect (and (delivered-right ?i)
                 (delivery-request-handled ?i ?z))
  )

  ;; button pressed, but ultrasonic finds no product
  ;; planner picks this branch autonomously when product-available is absent from :init
  (:action notify-unavailable-left
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-requested-left ?i ?z)
                        (not (product-available ?i ?z))
                        (not (delivery-unavailable-notified ?i ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i))
                        (not (delivery-request-handled ?i ?z)))
    :effect (and (delivery-unavailable-notified ?i ?z)
                 (delivery-request-handled ?i ?z))
  )

  (:action notify-unavailable-right
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-requested-right ?i ?z)
                        (not (product-available ?i ?z))
                        (not (delivery-unavailable-notified ?i ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i))
                        (not (delivery-request-handled ?i ?z)))
    :effect (and (delivery-unavailable-notified ?i ?z)
                 (delivery-request-handled ?i ?z))
  )

  (:action clear-unavailable-notice
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-unavailable-notified ?i ?z)
                        (product-available ?i ?z))
    :effect (not (delivery-unavailable-notified ?i ?z))
  )
)
