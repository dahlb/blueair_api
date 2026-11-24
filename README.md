# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/dahlb/blueair_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                  |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------------ | -------: | -------: | -------: | -------: | ------: | --------: |
| src/blueair\_api/\_\_init\_\_.py                      |       10 |        0 |        0 |        0 |    100% |           |
| src/blueair\_api/callbacks.py                         |       21 |        3 |        8 |        1 |     79% |20-\>22, 26-28 |
| src/blueair\_api/const.py                             |       12 |        0 |        0 |        0 |    100% |           |
| src/blueair\_api/device.py                            |      110 |       50 |       22 |        1 |     46% |28-46, 83, 88-152 |
| src/blueair\_api/device\_aws.py                       |      341 |       24 |       64 |       10 |     90% |168-179, 272-\>275, 293, 298, 371, 422-\>429, 440-442, 480-481, 496-\>exit, 524-527, 534, 544-546, 553, 556-557 |
| src/blueair\_api/errors.py                            |        9 |        0 |        0 |        0 |    100% |           |
| src/blueair\_api/http\_aws\_blueair.py                |      300 |       35 |       64 |        5 |     88% |442-454, 532, 542, 549-551, 565-\>569, 570, 591, 617-635, 640-664, 723-725 |
| src/blueair\_api/http\_blueair.py                     |      124 |       82 |       22 |        0 |     32% |62-64, 68-70, 95-102, 110-124, 136-145, 158-171, 184-193, 206-215, 232-244, 252-274, 278-295, 299-315, 319-335 |
| src/blueair\_api/intermediate\_representation\_aws.py |      130 |        5 |       64 |        5 |     95% |51, 57, 147-148, 208, 225-\>200 |
| src/blueair\_api/mqtt\_aws\_blueair.py                |      248 |        3 |       70 |        6 |     97% |401-\>exit, 417, 456-\>465, 511, 519-\>516, 533 |
| src/blueair\_api/region\_discovery.py                 |      180 |       25 |       66 |       12 |     84% |129-\>131, 141, 226-227, 236-238, 246-248, 262-263, 272-274, 288, 296-297, 299-300, 307-309, 355, 363-\>373, 404-405, 445-\>449 |
| src/blueair\_api/sku\_map.py                          |       12 |        3 |        4 |        0 |     69% |   478-480 |
| src/blueair\_api/util.py                              |       38 |       19 |       16 |        0 |     50% |46-58, 63-65, 73-87 |
| src/blueair\_api/util\_bootstrap.py                   |       20 |       11 |        2 |        0 |     41% |23-40, 56-77 |
| src/blueair\_api/util\_http.py                        |       41 |        3 |        6 |        0 |     94% |     89-91 |
| **TOTAL**                                             | **1596** |  **263** |  **408** |   **40** | **82%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/dahlb/blueair_api/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/dahlb/blueair_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/dahlb/blueair_api/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/dahlb/blueair_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fdahlb%2Fblueair_api%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/dahlb/blueair_api/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.