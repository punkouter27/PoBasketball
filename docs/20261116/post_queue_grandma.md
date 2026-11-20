# Post-queue: grandma skin in Unreal

- [10:47:26] waiting for the training queue to exit
- [10:51:28] training queue finished
- [11:06:07] build StreetballGymEditor: rc=0 (log C:\Users\punko\Downloads\_CODEMATT\PoBasketball\unreal\StreetballGym\Saved\Logs\grandma\build.log)
- [11:16:04] import: rc=0 ok=True (log C:\Users\punko\Downloads\_CODEMATT\PoBasketball\unreal\StreetballGym\Saved\Logs\grandma\import.log)

```nTraceback (most recent call last):
  File "C:\Users\punko\Downloads\_CODEMATT\PoBasketball\unreal\StreetballGym\Scripts\compare_bones.py", line 21, in <module>
    cand = {b["name"]: b["component_space"]["pos_cm"] for b in json.load(open(a.candidate, encoding="utf-8"))["bones"]}
                                                                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\punko\\Downloads\\_CODEMATT\\PoBasketball\\docs\\20261116\\grandma_bones_ue.json'
```

- [11:17:08] bind-joint check vs Manny: rc=1
- [11:18:35] automation: 14 passed, 2 failed; character mesh in tests: SK_Grandma (log C:\Users\punko\Downloads\_CODEMATT\PoBasketball\unreal\StreetballGym\Saved\Logs\grandma\tests.log)
- [11:18:35] done
